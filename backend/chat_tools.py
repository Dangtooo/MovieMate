"""TMDB function tools and small, deterministic movie ranking functions."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select

from .models import Watchlist
from .tmdb import GENRES, save_movies, select_trailer, tmdb_get


def today():
    return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat()


def rank_movies(
    movies: list[dict], sort_by: str = "rating", limit: int = 5
) -> list[dict]:
    """Deduplicate and sort verified candidates; rating uses Bayesian vote weighting.

    rating score = votes/(votes+100)*rating + 100/(votes+100)*6.
    Other orders: newest, shortest, popularity. Missing runtimes sort last.
    """
    unique = {m["id"]: m for m in movies if m.get("id") and not m.get("adult")}

    def key(m):
        votes = max(0, m.get("vote_count") or 0)
        rating = m.get("vote_average", m.get("rating", 0)) or 0
        weighted = (votes * rating + 600) / (votes + 100)
        if sort_by == "release_order":
            return (m.get("release_date") or "9999", m["id"])
        if sort_by == "newest":
            return (m.get("release_date") or "", weighted, m["id"])
        if sort_by == "shortest":
            return (-(m.get("runtime") or 100000), weighted, m["id"])
        if sort_by == "popularity":
            return (m.get("popularity") or 0, weighted, m["id"])
        return (weighted, votes, m["id"])

    return sorted(unique.values(), key=key, reverse=sort_by != "release_order")[
        : max(1, min(limit, 20))
    ]


def movie_card(row: dict) -> dict:
    poster = row.get("poster_path") or ""
    trailer = select_trailer(row.get("videos", {}).get("results", []))
    return {
        "id": row["id"],
        "title": row.get("title") or row.get("original_title", ""),
        "release_year": (row.get("release_date") or "")[:4],
        "rating": row.get("vote_average") or 0,
        "poster_url": (
            "https://image.tmdb.org/t/p/w200" + poster
            if re.fullmatch(r"/[\w.-]+\.(jpg|png|webp)", poster)
            else None
        ),
        "trailer_url": (
            "https://www.youtube.com/watch?v=" + trailer["key"] if trailer else None
        ),
        "reason": " · ".join(
            filter(
                None,
                [
                    f"TMDB {row.get('vote_average') or 0:.1f}/10",
                    f"{row['runtime']} phút" if row.get("runtime") else "",
                ],
            )
        ),
    }


class MovieTools:
    """Request-scoped tools. Only API-verified rows may become UI movie cards."""

    def __init__(self, db, evidence: dict, watched_ids: set[int]):
        self.db = db
        self.evidence = evidence.copy()
        self.watched_ids = watched_ids
        self.calls = 0

    def _get(self, path, **params):
        self.calls += 1
        if self.calls > 30:
            raise ValueError(
                "Đã đạt giới hạn tra cứu cho câu hỏi này; hãy thu hẹp yêu cầu."
            )
        return tmdb_get(path, **params)

    def _remember(
        self, rows, sort_by="rating", exclude_watched=False, released_only=True
    ):
        rows = [m for m in rows if m.get("id") and not m.get("adult")]
        if released_only:
            rows = [
                m
                for m in rows
                if m.get("release_date") and m["release_date"] <= today()
            ]
        if exclude_watched:
            rows = [m for m in rows if m["id"] not in self.watched_ids]
        rows = rank_movies(rows, sort_by, 20)
        save_movies(self.db, rows)
        for row in rows:
            self.evidence[row["id"]] = row
        return {
            "movies": [self._summary(m) for m in rows[:8]],
            "source": "TMDB",
            "sort_by": sort_by,
        }

    @staticmethod
    def _summary(m):
        return {
            **movie_card(m),
            "overview": (m.get("overview") or "")[:500],
            "runtime": m.get("runtime"),
            "release_date": m.get("release_date"),
            "genres": [
                GENRES[g]
                for g in (m.get("genre_ids") or [g["id"] for g in m.get("genres", [])])
                if g in GENRES
            ],
        }

    def search_movies(self, title: str, year: int = 0) -> dict:
        """Find movie titles on TMDB. year=0 means unspecified. Ask user when ambiguous."""
        params = {"query": title[:150], "include_adult": False}
        if year:
            params["year"] = year
        try:
            rows = self._get("search/movie", **params).get("results", [])
            return self._remember(rows, "popularity", released_only=False)
        except (HTTPException, ValueError) as exc:
            return self._error(exc)

    def discover_movies(
        self,
        genres: list[str],
        excluded_genres: list[str],
        keywords: list[str],
        actors: list[str],
        directors: list[str],
        language: str = "",
        year_from: int = 0,
        year_to: int = 0,
        min_rating: float = 0,
        min_runtime: int = 0,
        max_runtime: int = 0,
        sort_by: str = "rating",
        upcoming: bool = False,
        watch_provider: str = "",
        watch_country: str = "VN",
    ) -> dict:
        """Discover films with hard filters, excluding watched films.

        Supply genre names in English or Vietnamese (use list_genres first), person
        names, English topic keywords, ISO-639-1 language (or OR codes ja|ko|zh).
        Empty lists/zero mean no filter. Actors/directors are combined AND.
        Sort: rating, newest, popularity, shortest (detail check of up to 10 candidates).
        upcoming only if explicitly asked. watch_provider e.g. Netflix, Disney Plus;
        watch_country is ISO country (VN default), subscription streaming only.
        """
        try:
            if sort_by not in {"rating", "newest", "popularity", "shortest"}:
                raise ValueError("Tiêu chí xếp hạng không hợp lệ.")
            if (
                not 0 <= min_rating <= 10
                or not 0 <= min_runtime <= 600
                or not 0 <= max_runtime <= 600
            ):
                raise ValueError("Điểm hoặc thời lượng không hợp lệ.")
            if (
                year_from
                and year_to
                and year_from > year_to
                or max_runtime
                and min_runtime > max_runtime
            ):
                raise ValueError("Khoảng năm hoặc thời lượng bị đảo ngược.")
            params = {
                "include_adult": False,
                "sort_by": {
                    "rating": "vote_average.desc",
                    "newest": "primary_release_date.desc",
                    "shortest": "popularity.desc",
                    "popularity": "popularity.desc",
                }[sort_by],
            }
            # Rating lists need a vote floor; an unrated new release is still valid.
            if sort_by == "rating":
                params["vote_count.gte"] = 100
            params[
                "primary_release_date.gte" if upcoming else "primary_release_date.lte"
            ] = today()
            if upcoming:
                from datetime import date, timedelta

                params["primary_release_date.gte"] = (
                    date.fromisoformat(today()) + timedelta(days=1)
                ).isoformat()
            for field, value in [
                ("vote_average.gte", min_rating),
                ("with_runtime.gte", min_runtime),
                ("with_runtime.lte", max_runtime),
            ]:
                if value:
                    params[field] = value
            if max_runtime and not min_runtime:
                params["with_runtime.gte"] = 1
            if language:
                if not re.fullmatch(r"[a-z]{2}(?:\|[a-z]{2}){0,19}", language):
                    raise ValueError("Mã ngôn ngữ không hợp lệ.")
                params["with_original_language"] = language
            if year_from:
                params["primary_release_date.gte"] = max(
                    f"{year_from:04}-01-01", params.get("primary_release_date.gte", "")
                )
            if year_to:
                params["primary_release_date.lte"] = min(
                    f"{year_to:04}-12-31",
                    params.get("primary_release_date.lte", "9999"),
                )
            if watch_provider:
                if not re.fullmatch("[A-Z]{2}", watch_country):
                    raise ValueError("Mã quốc gia nền tảng không hợp lệ.")
                providers = self._get(
                    "watch/providers/movie", watch_region=watch_country
                ).get("results", [])
                matches = [
                    p
                    for p in providers
                    if p["provider_name"].casefold() == watch_provider.casefold()
                ]
                if len(matches) != 1:
                    return {
                        "movies": [],
                        "message": "Chưa xác định được nền tảng tại quốc gia này.",
                        "provider_names": [p["provider_name"] for p in providers[:20]],
                    }
                params.update(
                    {
                        "watch_region": watch_country,
                        "with_watch_providers": str(matches[0]["provider_id"]),
                        "with_watch_monetization_types": "flatrate",
                    }
                )
            if genres or excluded_genres:
                vi = self._get("genre/movie/list").get("genres", [])
                en = self._get("genre/movie/list", language="en-US").get("genres", [])
                names = {g["name"].casefold(): g["id"] for g in vi + en}
                for field, values in [
                    ("with_genres", genres),
                    ("without_genres", excluded_genres),
                ]:
                    if any(name.casefold() not in names for name in values):
                        raise ValueError(
                            "Không nhận diện được thể loại; hãy dùng list_genres."
                        )
                    if values:
                        params[field] = ",".join(
                            str(names[n.casefold()]) for n in values[:5]
                        )
            for field, values in [
                ("with_cast", actors),
                ("with_crew", directors),
                ("with_keywords", keywords),
            ]:
                ids = []
                for name in values[:3]:
                    results = self._get(
                        (
                            "search/keyword"
                            if field == "with_keywords"
                            else "search/person"
                        ),
                        query=name[:150],
                    ).get("results", [])
                    if field == "with_crew":
                        results = [
                            p
                            for p in results
                            if p.get("known_for_department") == "Directing"
                        ]
                    exact = [
                        p
                        for p in results
                        if p.get("name", "").casefold() == name.casefold()
                    ]
                    matches = exact or results
                    if not matches:
                        return {
                            "movies": [],
                            "message": f"Không tìm thấy {name} trên TMDB.",
                        }
                    if len(exact) > 1:
                        return {
                            "movies": [],
                            "message": f"Có nhiều người/từ khóa tên {name}; hãy hỏi thêm để phân biệt.",
                        }
                    ids.append(str(matches[0]["id"]))
                if ids:
                    params[field] = ",".join(ids)
            rows = []
            for page in (1, 2):
                data = self._get("discover/movie", page=page, **params)
                rows.extend(data.get("results", []))
                if page >= data.get("total_pages", 1):
                    break
            # with_crew includes non-director jobs. Verify exact Director credits.
            if directors:
                director_ids = set(map(int, params["with_crew"].split(",")))
                verified = []
                for row in rows[:20]:
                    credits = self._get(f"movie/{row['id']}/credits")
                    actual = {
                        p["id"]
                        for p in credits.get("crew", [])
                        if p.get("job") == "Director"
                    }
                    if director_ids <= actual:
                        verified.append(row)
                rows = verified
            if sort_by == "shortest":
                # TMDB list rows omit runtime. Fetch a bounded candidate set first.
                count = min(10, max(0, 30 - self.calls))
                rows = [
                    {**row, **self._get(f"movie/{row['id']}")} for row in rows[:count]
                ]
                rows = [row for row in rows if row.get("runtime")]
            return self._remember(
                rows, sort_by, exclude_watched=True, released_only=not upcoming
            )
        except (HTTPException, ValueError) as exc:
            return self._error(exc)

    def list_genres(self) -> dict:
        """Get valid English and Vietnamese genre names for discovery filters."""
        try:
            return {
                "vietnamese": self._get("genre/movie/list").get("genres", []),
                "english": self._get("genre/movie/list", language="en-US").get(
                    "genres", []
                ),
            }
        except (HTTPException, ValueError) as exc:
            return self._error(exc)

    def movie_details(self, movie_id: int) -> dict:
        """Get synopsis, cast, directors, runtime, certification, reviews and trailer.

        movie_id MUST come from a tool result or verified conversation history.
        """
        if movie_id not in self.evidence:
            return {"error": "Hãy tìm phim theo tên trước; không tự đoán ID."}
        try:
            row = self._get(
                f"movie/{movie_id}",
                append_to_response="credits,videos,release_dates,reviews",
            )
            if not select_trailer(row.get("videos", {}).get("results", [])):
                try:
                    videos = self._get(f"movie/{movie_id}/videos", language="en-US")
                    row = {**row, "videos": videos}
                except (HTTPException, ValueError):
                    pass  # Optional trailer failure must not discard valid details.
            self.evidence[movie_id] = row
            save_movies(self.db, [row], details=True)
            return {
                **self._summary(row),
                "cast": [
                    p["name"] for p in row.get("credits", {}).get("cast", [])[:12]
                ],
                "directors": [
                    p["name"]
                    for p in row.get("credits", {}).get("crew", [])
                    if p.get("job") == "Director"
                ],
                "certifications": row.get("release_dates", {}).get("results", []),
                "tagline": row.get("tagline"),
                "budget": row.get("budget"),
                "revenue": row.get("revenue"),
                "reviews": [
                    {"author": r.get("author"), "content": r.get("content", "")[:400]}
                    for r in row.get("reviews", {}).get("results", [])[:2]
                ],
                "source": "TMDB",
            }
        except (HTTPException, ValueError) as exc:
            return self._error(exc)

    def related_movies(self, movie_id: int, sort_by: str = "rating") -> dict:
        """Get TMDB recommendations/similar films; movie_id must be verified first."""
        if movie_id not in self.evidence:
            return {"error": "Hãy tìm phim gốc trước; không tự đoán ID."}
        try:
            rows = self._get(f"movie/{movie_id}/recommendations").get("results", [])
            rows += self._get(f"movie/{movie_id}/similar").get("results", [])
            return self._remember(
                [m for m in rows if m.get("id") != movie_id],
                sort_by,
                exclude_watched=True,
            )
        except (HTTPException, ValueError) as exc:
            return self._error(exc)

    def find_similar_movies(
        self, title: str, year: int = 0, sort_by: str = "rating"
    ) -> dict:
        """Find films like a named movie, e.g. 'phim giống Incantation'.

        Resolves the reference and gets recommendations in ONE tool invocation.
        year=0 if unspecified. Ambiguous titles return choices; ask user to clarify.
        """
        try:
            result = self.search_movies(title, year)
            if result.get("error"):
                return result
            candidates = [self.evidence[m["id"]] for m in result.get("movies", [])]
            exact = [
                m
                for m in candidates
                if title.casefold()
                in {
                    m.get("title", "").casefold(),
                    m.get("original_title", "").casefold(),
                }
            ]
            matches = exact or candidates
            if len(matches) != 1:
                return {
                    "movies": result.get("movies", []),
                    "needs_clarification": True,
                    "message": (
                        "Hãy xác nhận tên/năm phim gốc."
                        if matches
                        else "Không tìm thấy phim gốc trên TMDB."
                    ),
                }
            source = matches[0]
            related = self.related_movies(source["id"], sort_by)
            return {**related, "reference": self._summary(source)}
        except (HTTPException, ValueError) as exc:
            return self._error(exc)

    def person_information(
        self,
        name: str,
        role: str = "actor",
        known_for_movie: str = "",
        upcoming: bool = False,
    ) -> dict:
        """Look up an actor/director's biography and filmography by NAME.

        Examples: 'Nolan là ai?', '5 phim của Tom Hanks', 'phim sắp ra của Nolan'.
        role: actor, director, writer, producer. known_for_movie disambiguates names.
        Director filmography checks exact Director job, not general crew membership.
        """
        if role not in {"actor", "director", "writer", "producer"}:
            return {"error": "Vai trò cần là actor, director, writer hoặc producer."}
        try:
            people = [
                p
                for p in self._get(
                    "search/person", query=name[:150], include_adult=False
                ).get("results", [])
                if not p.get("adult")
            ]
            exact = [
                p for p in people if p.get("name", "").casefold() == name.casefold()
            ]
            matches = exact or people
            if known_for_movie:
                matches = [
                    p
                    for p in matches
                    if any(
                        known_for_movie.casefold()
                        in {
                            m.get("title", "").casefold(),
                            m.get("original_title", "").casefold(),
                        }
                        for m in p.get("known_for", [])
                    )
                ]
            if len(matches) != 1:
                return {
                    "movies": [],
                    "needs_clarification": bool(matches),
                    "message": (
                        "Cần xác nhận người nào."
                        if matches
                        else "Không tìm thấy người phù hợp."
                    ),
                    "people": [
                        {
                            "name": p["name"],
                            "known_for": [
                                m.get("title")
                                for m in p.get("known_for", [])
                                if m.get("title")
                            ],
                        }
                        for p in matches[:5]
                    ],
                }
            person = self._get(
                f"person/{matches[0]['id']}", append_to_response="movie_credits"
            )
            credits = person.get("movie_credits", {})
            jobs = {
                "director": {"Director"},
                "writer": {"Writer", "Screenplay", "Story"},
                "producer": {"Producer"},
            }
            rows = (
                credits.get("cast", [])
                if role == "actor"
                else [m for m in credits.get("crew", []) if m.get("job") in jobs[role]]
            )
            total = len({m["id"] for m in rows})
            if upcoming:
                rows = [m for m in rows if m.get("release_date", "") > today()]
            result = self._remember(
                rows,
                "release_order" if upcoming else "rating",
                released_only=not upcoming,
            )
            return {
                **result,
                "person": {
                    "name": person.get("name"),
                    "birthday": person.get("birthday"),
                    "deathday": person.get("deathday"),
                    "place_of_birth": person.get("place_of_birth"),
                    "biography": (person.get("biography") or "")[:1000],
                },
                "role": role,
                "total_credits": total,
            }
        except (HTTPException, ValueError) as exc:
            return self._error(exc)

    def movie_collection(self, movie_id: int) -> dict:
        """List a verified film's franchise/sequels in RELEASE order, including future parts.

        For 'Harry Potter có mấy phần?', 'xem John Wick thứ tự nào?'. Search a movie
        first. Release order is NOT story chronology; do not invent chronology.
        """
        if movie_id not in self.evidence:
            return {"error": "Hãy tìm một phim trong loạt trước, không tự đoán ID."}
        try:
            row = self._get(f"movie/{movie_id}")
            collection = row.get("belongs_to_collection")
            if not collection:
                return {
                    "movies": [],
                    "message": "TMDB không gắn phim này với loạt phim nào.",
                }
            data = self._get(f"collection/{collection['id']}")
            parts = [m for m in data.get("parts", []) if not m.get("adult")]
            result = self._remember(parts, "release_order", released_only=False)
            return {
                **result,
                "collection": data.get("name"),
                "part_count": len(parts),
                "release_order": [
                    {
                        "id": m["id"],
                        "title": m.get("title"),
                        "release_date": m.get("release_date"),
                        "released": bool(
                            m.get("release_date") and m["release_date"] <= today()
                        ),
                    }
                    for m in rank_movies(parts, "release_order", 20)
                ],
                "message": "Thứ tự phát hành theo TMDB; chưa xác minh thứ tự thời gian trong cốt truyện.",
            }
        except (HTTPException, ValueError) as exc:
            return self._error(exc)

    def compare_movies(self, movie_ids: list[int]) -> dict:
        """Compare 2-5 verified movies: synopsis, runtime, rating, year, genres, directors.

        Use for 'A hay B?', 'phim nào ngắn hơn?', 'phim nào hợp xem gia đình?'.
        Fetches missing details without another model roundtrip. No unverified IDs.
        Age certification does not guarantee suitability; do not invent content warnings.
        """
        if not 2 <= len(set(movie_ids)) <= 5 or any(
            mid not in self.evidence for mid in movie_ids
        ):
            return {"error": "Cần 2 đến 5 ID phim đã được tra cứu."}
        movies, errors = [], []
        for mid in dict.fromkeys(movie_ids):
            details = self.movie_details(mid)
            if details.get("error"):
                errors.append({"id": mid, "error": details["error"]})
            else:
                movies.append(
                    {
                        k: details.get(k)
                        for k in [
                            "id",
                            "title",
                            "overview",
                            "runtime",
                            "rating",
                            "release_date",
                            "genres",
                            "directors",
                            "certifications",
                        ]
                    }
                )
        return {"movies": movies, "errors": errors, "source": "TMDB"}

    def movie_lists(self, category: str = "trending", region: str = "VN") -> dict:
        """Get trending, now_playing, upcoming, popular or top_rated movies.

        region is an uppercase ISO country code for cinema lists, default VN.
        """
        if category not in {
            "trending",
            "now_playing",
            "upcoming",
            "popular",
            "top_rated",
        } or not re.fullmatch("[A-Z]{2}", region):
            return {"error": "Danh sách hoặc mã quốc gia không hợp lệ."}
        try:
            rows = self._get(
                (
                    "trending/movie/week"
                    if category == "trending"
                    else f"movie/{category}"
                ),
                region=region,
            ).get("results", [])
            if category == "upcoming":
                rows = [m for m in rows if m.get("release_date", "") > today()]
            return self._remember(
                rows,
                (
                    "rating"
                    if category == "top_rated"
                    else "newest" if category == "upcoming" else "popularity"
                ),
                exclude_watched=True,
                released_only=category != "upcoming",
            )
        except (HTTPException, ValueError) as exc:
            return self._error(exc)

    def watch_providers(self, movie_id: int, country: str = "VN") -> dict:
        """Find legal streaming/rent/buy providers for a verified film and country."""
        if movie_id not in self.evidence or not re.fullmatch("[A-Z]{2}", country):
            return {"error": "Hãy tìm phim trước và dùng mã quốc gia ISO hợp lệ."}
        try:
            result = (
                self._get(f"movie/{movie_id}/watch/providers")
                .get("results", {})
                .get(country, {})
            )
            return {
                "movie_id": movie_id,
                "country": country,
                "source": "TMDB / JustWatch",
                "link": result.get("link"),
                "stream": [p["provider_name"] for p in result.get("flatrate", [])],
                "rent": [p["provider_name"] for p in result.get("rent", [])],
                "buy": [p["provider_name"] for p in result.get("buy", [])],
                "message": (
                    "Chưa có dữ liệu nơi xem cho quốc gia này."
                    if not result
                    else "Khả dụng có thể thay đổi; kiểm tra tại nhà cung cấp."
                ),
            }
        except (HTTPException, ValueError) as exc:
            return self._error(exc)

    def rank_candidates(
        self, movie_ids: list[int], sort_by: str = "rating", limit: int = 5
    ) -> dict:
        """Compare/rank verified films: rating (vote weighted), newest, shortest, popularity.

        Use for follow-ups like 'which is shortest?'. Unknown runtimes are excluded
        for shortest; fetch movie_details first for complete comparisons.
        """
        if any(mid not in self.evidence for mid in movie_ids):
            return {"error": "Chỉ xếp hạng ID phim đã tra cứu."}
        if sort_by not in {"rating", "newest", "shortest", "popularity"}:
            return {"error": "Tiêu chí xếp hạng không hợp lệ."}
        rows = [self.evidence[mid] for mid in movie_ids]
        missing = [
            m["id"] for m in rows if sort_by == "shortest" and not m.get("runtime")
        ]
        if sort_by == "shortest":
            rows = [m for m in rows if m.get("runtime")]
        return {
            "movies": [self._summary(m) for m in rank_movies(rows, sort_by, limit)],
            "missing_runtime_ids": missing,
            "sort_by": sort_by,
        }

    @staticmethod
    def _error(exc):
        return {
            "error": exc.detail if isinstance(exc, HTTPException) else str(exc),
            "movies": [],
        }

    def functions(self):
        return [
            self.search_movies,
            self.discover_movies,
            self.list_genres,
            self.movie_details,
            self.related_movies,
            self.movie_lists,
            self.watch_providers,
            self.rank_candidates,
            self.find_similar_movies,
            self.person_information,
            self.movie_collection,
            self.compare_movies,
        ]


def watched_movies(db, user_id):
    if not user_id:
        return set()
    return set(
        db.scalars(
            select(Watchlist.movie_tmdb_id).where(
                Watchlist.user_id == user_id, Watchlist.status == "watched"
            )
        )
    )
