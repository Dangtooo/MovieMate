"""Seven TMDB tools. Models supply names; only Python resolves catalog IDs."""

import re
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from .config import get_settings
from .models import Movie, Watchlist
from .preference_rules import describe_preferences, extract_reference, normalize, requested_language, split_title_year, wants_more
from .queries import has_any_genre
from .schemas import ChatIn, Preferences
from .similarity import recommend_similar, resolve_reference
from .chat_metadata import english_keywords, full_details_text, genre_ids, official_trailer
from .tmdb import GENRES, save_movies, tmdb_get
from .query_policy import sort_cards, sort_rows
from . import query_policy


class _DiscoverFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    genre_ids: list[int] = Field(default_factory=list, max_length=5)
    min_year: int | None = Field(default=None, ge=1900, le=2100)
    max_year: int | None = Field(default=None, ge=1900, le=2100)
    min_rating: float | None = Field(default=None, ge=0, le=10)
    sort_by: Literal["newest", "rating"] = "newest"
    with_keywords: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=5)
    excluded_genre_ids: list[int] = Field(default_factory=list, max_length=5)
    min_runtime: int | None = Field(default=None, ge=1, le=600)
    max_runtime: int | None = Field(default=None, ge=1, le=600)
    language: str | None = Field(default=None, max_length=59, pattern=r"^[a-z]{2}(?:\|[a-z]{2}){0,19}$")


class DiscoverArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    genres: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(default_factory=list, max_length=5)
    original_language: str | None = Field(default=None, max_length=59, pattern=r"^[a-z]{2}(?:\|[a-z]{2}){0,19}$")
    release_year_from: int | None = Field(default=None, ge=1900, le=2100)
    release_year_to: int | None = Field(default=None, ge=1900, le=2100)
    min_rating: float | None = Field(default=None, ge=0, le=10)
    max_runtime: int | None = Field(default=None, ge=1, le=600)
    keywords_text: str | None = Field(default=None, max_length=400)
    sort_by: Literal["newest", "rating"] = "newest"
    excluded_genres: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(default_factory=list, max_length=5)
    min_runtime: int | None = Field(default=None, ge=1, le=600)


class PeopleArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    person_names: list[Annotated[str, Field(min_length=1, max_length=150)]] = Field(min_length=1, max_length=5)
    role: Literal["actor", "director"]
    known_for_movie: str | None = Field(default=None, min_length=1, max_length=150)


class TitleSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=150)


class MovieTitleArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    movie_title: str = Field(min_length=1, max_length=150)
    year: int | None = Field(default=None, ge=1900, le=2100)


class DetailsArgs(MovieTitleArgs):
    region: str = Field(default="VN", pattern=r"^[A-Z]{2}$")


class ProvidersArgs(MovieTitleArgs):
    country_code: str = Field(default="VN", pattern=r"^[A-Z]{2}$")


class TrendingArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    category: Literal["trending", "now_playing", "upcoming", "top_rated"]
    time_window: Literal["day", "week"] = "week"
    region: str = Field(default="VN", pattern=r"^[A-Z]{2}$")


ARGUMENTS = {
    "discover_movies": DiscoverArgs,
    "search_movies_by_people": PeopleArgs,
    "get_similar_and_recommended_movies": MovieTitleArgs,
    "get_trending_or_cinema_movies": TrendingArgs,
    "get_movie_full_details": DetailsArgs,
    "get_movie_watch_providers": ProvidersArgs,
    "search_movie_by_title": TitleSearchArgs,
}
DESCRIPTIONS = {
    "discover_movies": "Tìm theo tên thể loại, ngôn ngữ ISO 639-1, năm, điểm, thời lượng và chủ đề. LUÔN dịch từ khóa tâm trạng/cốt truyện sang tiếng Anh trong keywords_text (chữa lành -> healing; du hành thời gian -> time travel); không thay chủ đề bằng thể loại chung. Python tự tìm ID từ khóa và thể loại; không gửi ID. Dùng dấu phẩy giữa các từ khóa gần nghĩa để mở rộng tập ứng viên (OR), sau đó chọn theo đúng nội dung yêu cầu. Giữ tiêu chí phiên chưa bị thay đổi.",
    "search_movies_by_people": "Tìm phim có diễn viên (role=actor) hoặc do đạo diễn thực hiện (role=director). person_names là tên đầy đủ, KHÔNG phải ID. Python tra từng tên và kết hợp AND; kiểm tra đúng job Director. Nếu cần phân biệt người trùng tên và người dùng nêu phim họ từng làm, truyền tên phim đó trong known_for_movie; không tự đoán phim mốc.",
    "get_similar_and_recommended_movies": "Tìm tên phim gốc rồi lấy TMDB recommendations, phân tích mô tả/chủ đề để chọn phim gần nội dung. Dùng cho giống/tương tự, không thay bằng discover thể loại chung. Không đoán năm phim gốc nếu người dùng chưa nói.",
    "get_trending_or_cinema_movies": "Tra phim thịnh hành (trending, ngày/tuần trên TMDB), đang chiếu (now_playing), sắp chiếu (upcoming), hoặc điểm cao (top_rated). region mặc định VN, dùng cho danh sách rạp; không nhầm phim thịnh hành với phim đang chiếu.",
    "get_movie_full_details": "Tra tên phim để lấy nội dung chi tiết, thời lượng, đạo diễn, 5 diễn viên chính, phân loại độ tuổi theo region và trailer YouTube chính thức. Dùng cả khi hỏi phim trước đó có trailer hay không. Không tự tạo thông tin hoặc URL trailer.",
    "get_movie_watch_providers": "Tra nơi xem/thuê/mua của phim theo country_code ISO 3166-1, mặc định VN. Đọc dữ liệu TMDB/JustWatch theo đúng quốc gia, không tự đoán Netflix hoặc dùng kết quả quốc gia khác.",
    "search_movie_by_title": "Tìm tên phim hoặc thương hiệu phim (ví dụ John Wick) qua search/movie. Mặc định mới nhất trước, chỉ theo điểm khi người dùng hỏi chất lượng. query là tên đọc được, không phải ID.",
}


def declarations():
    return [{"name": name, "description": DESCRIPTIONS[name], "parameters": model.model_json_schema()}
            for name, model in ARGUMENTS.items()]


def snapshot(movie):
    poster = movie.poster_path or ""
    return {"id": movie.tmdb_id, "title": movie.title,
            "release_date": movie.release_date.isoformat() if movie.release_date else None,
            "release_year": str(movie.release_date.year) if movie.release_date else "",
            "rating": movie.tmdb_rating or 0,
            "poster_url": "https://image.tmdb.org/t/p/w200" + poster if re.fullmatch(r"/[\w.-]+\.(?:jpg|png|webp)", poster, re.I) else None,
            "trailer_url": None,
            "runtime": movie.runtime if movie.details_fetched_at else None, "overview": movie.overview[:600],
            "genre_ids": movie.genre_ids or [], "language": movie.original_language}


def filtered_query(prefs, user_id, cutoff=None):
    stmt = select(Movie)
    cutoff = cutoff or query_policy.today()
    stmt = stmt.where(Movie.release_date > cutoff) if prefs.release_scope == "upcoming" else stmt.where(Movie.release_date <= cutoff)
    if prefs.genre_ids:
        stmt = stmt.where(has_any_genre(prefs.genre_ids))
    if prefs.excluded_genre_ids:
        stmt = stmt.where(~has_any_genre(prefs.excluded_genre_ids))
    if prefs.min_year:
        stmt = stmt.where(Movie.release_date >= f"{prefs.min_year}-01-01")
    if prefs.max_year:
        stmt = stmt.where(Movie.release_date <= f"{prefs.max_year}-12-31")
    if prefs.language:
        stmt = stmt.where(Movie.original_language.in_(prefs.language.split("|")))
    if user_id:
        stmt = stmt.where(Movie.tmdb_id.not_in(select(Watchlist.movie_tmdb_id).where(
            Watchlist.user_id == user_id, Watchlist.status == "watched")))
    return stmt


def reason_for(movie, prefs):
    bits = [GENRES[g] for g in movie.genre_ids or [] if g in prefs.genre_ids and g in GENRES]
    if movie.runtime and movie.details_fetched_at:
        bits.append(f"{movie.runtime} phút")
    if movie.release_date:
        bits.append(f"phát hành năm {movie.release_date.year}")
    bits.append(f"TMDB {movie.tmdb_rating or 0:g}/10")
    return "; ".join(bits) + "."


class MovieTools:
    def __init__(self, db, state, user_id, message):
        self.db, self.state, self.user_id, self.message = db, state, user_id, message
        self.cutoff = query_policy.today()
        self.result = None
        self.results = []
        self.called = []
        self.min_rating = state.tool_options.get("min_rating")
        self.sort_by = state.preferences.sort_by
        self.keywords = []
        self.discovery_filters = {}
        self.allowed_ids = None

    def execute(self, name, arguments):
        if name not in ARGUMENTS:
            raise ValueError("Công cụ không được hỗ trợ.")
        args = ARGUMENTS[name].model_validate(arguments)
        explicit = extract_reference(self.message)
        if explicit and name in {"discover_movies", "search_movie_by_title", "search_movies_by_people"}:
            name = "get_similar_and_recommended_movies"
        if name == "get_similar_and_recommended_movies" and explicit:
            # The user-supplied name/year wins over model guesses about remakes.
            args = MovieTitleArgs(movie_title=explicit[0], year=explicit[1])
        self.called.append(name)
        if self.state.pending_action and self.state.pending_action["tool"] != name:
            self.state.pending.clear()
            self.state.pending_action.clear()
        if not get_settings().tmdb_access_token:
            self.result = {"reply": "Chưa kết nối kho phim TMDB nên mình chưa thể tra cứu phim theo yêu cầu. Hãy cấu hình kết nối TMDB rồi thử lại nhé.", "movies": []}
            return self.result
        try:
            current = getattr(self, name)(args)
        except HTTPException:
            current = {"reply": "Kho phim TMDB đang không phản hồi. Mình chưa thể xác thực gợi ý mới; bạn thử lại sau nhé.", "movies": []}
        self.results.append(current)
        if current.get("action"):
            self.result = current
        else:
            cards = {movie["id"]: movie for result in self.results if not result.get("action") for movie in result["movies"]}
            replies = list(dict.fromkeys(result["reply"] for result in self.results if not result.get("action")))
            self.result = {"reply": "\n\n".join(replies), "movies": sort_cards(list(cards.values()), self.state.preferences.sort_by)[:20]}
        return current

    def finish_rows(self, rows, reply, reasons=None, minimum_votes=0):
        rows = sort_rows(rows, self.state.preferences.sort_by, minimum_votes,
                         release_scope=self.state.preferences.release_scope, cutoff=self.cutoff)
        save_movies(self.db, [r for r in rows if not r.get("adult")])
        ids = [r["id"] for r in rows if not r.get("adult") and r.get("id")]
        stmt = filtered_query(self.state.preferences, self.user_id, self.cutoff).where(Movie.tmdb_id.in_(ids))
        movies = list(self.db.scalars(stmt))
        if self.allowed_ids is not None:
            movies = [m for m in movies if m.tmdb_id in self.allowed_ids]
        # Preserve the TMDB/tool ordering rather than database primary-key order.
        order = {mid: index for index, mid in enumerate(ids)}
        movies.sort(key=lambda m: order[m.tmdb_id])
        if self.state.preferences.max_runtime or self.state.preferences.min_runtime:
            missing = [m.tmdb_id for m in movies[:10] if not m.runtime or not m.details_fetched_at]
            def details_for(mid):
                try:
                    return tmdb_get(f"movie/{mid}", append_to_response="credits,videos")
                except HTTPException:
                    return None
            with ThreadPoolExecutor(max_workers=4) as executor:
                details = list(executor.map(details_for, missing))
            save_movies(self.db, [d for d in details if d], details=True)
            allowed = set(self.db.scalars(filtered_query(self.state.preferences, self.user_id, self.cutoff).with_only_columns(Movie.tmdb_id)))
            movies = [m for m in movies if m.tmdb_id in allowed and m.runtime and m.details_fetched_at and
                      (not self.state.preferences.max_runtime or m.runtime <= self.state.preferences.max_runtime) and
                      (not self.state.preferences.min_runtime or m.runtime >= self.state.preferences.min_runtime)]
        if self.min_rating is not None:
            movies = [m for m in movies if m.tmdb_rating >= self.min_rating]
        cards = [{**snapshot(m), "reason": (reasons or {}).get(m.tmdb_id) or reason_for(m, self.state.preferences)} for m in movies[:20]]
        if not cards:
            reply = "Chưa có phim thỏa các tiêu chí trong kết quả TMDB vừa tra cứu. Bạn muốn nới điều kiện nào?"
        return {"reply": reply, "movies": cards}

    def discover_movies(self, args):
        mapping = {"original_language": "language", "release_year_from": "min_year", "release_year_to": "max_year"}
        values = {mapping.get(field, field): getattr(args, field) for field in args.model_fields_set
                  if field not in {"genres", "excluded_genres", "keywords_text"}}
        try:
            if "genres" in args.model_fields_set:
                values["genre_ids"] = genre_ids(args.genres)
            if "excluded_genres" in args.model_fields_set:
                values["excluded_genre_ids"] = genre_ids(args.excluded_genres)
            if "keywords_text" in args.model_fields_set:
                values["with_keywords"] = english_keywords(args.keywords_text or "")
        except ValueError as error:
            return {"reply": str(error) + " Bạn mô tả lại yêu cầu nhé.", "movies": []}
        explicit_language, language = requested_language(self.message)
        if explicit_language:
            values["language"] = language
        return self._discover(_DiscoverFilters(**values))

    def _discover(self, args):
        prefs = self.state.preferences
        supplied = args.model_fields_set
        for field in ("genre_ids", "excluded_genre_ids", "min_year", "max_year", "min_runtime", "max_runtime", "language"):
            if field in supplied:
                setattr(prefs, field, getattr(args, field))
        prefs.genre_ids = [g for g in prefs.genre_ids if g in GENRES and g not in prefs.excluded_genre_ids]
        if prefs.min_year and prefs.max_year and prefs.min_year > prefs.max_year:
            return {"reply": "Khoảng năm đang mâu thuẫn. Bạn muốn tìm từ năm nào đến năm nào?", "movies": []}
        if prefs.min_runtime and prefs.max_runtime and prefs.min_runtime > prefs.max_runtime:
            return {"reply": "Khoảng thời lượng đang mâu thuẫn. Bạn muốn tìm từ bao nhiêu đến bao nhiêu phút?", "movies": []}
        for option in ("min_rating", "with_keywords"):
            if option in supplied:
                self.state.tool_options[option] = getattr(args, option)
            elif option in self.state.tool_options:
                setattr(args, option, self.state.tool_options[option])
        self.min_rating, self.sort_by, self.keywords = args.min_rating, prefs.sort_by, args.with_keywords
        self.state.tool_options.pop("sort_by", None)
        params = {"sort_by": "vote_average.desc" if prefs.sort_by == "rating" else "primary_release_date.desc", "include_adult": "false"}
        if prefs.sort_by == "rating":
            params["vote_count.gte"] = 50
        if prefs.genre_ids:
            params["with_genres"] = "|".join(map(str, prefs.genre_ids))
        if prefs.excluded_genre_ids:
            params["without_genres"] = ",".join(map(str, prefs.excluded_genre_ids))
        if prefs.min_year:
            params["primary_release_date.gte"] = f"{prefs.min_year}-01-01"
        if prefs.max_year:
            params["primary_release_date.lte"] = f"{prefs.max_year}-12-31"
        if prefs.release_scope == "upcoming":
            params["primary_release_date.gte"] = max(params.get("primary_release_date.gte", ""), (self.cutoff + timedelta(days=1)).isoformat())
        else:
            params["primary_release_date.lte"] = min(params.get("primary_release_date.lte", self.cutoff.isoformat()), self.cutoff.isoformat())
        if params.get("primary_release_date.gte", "") > params.get("primary_release_date.lte", "9999-12-31"):
            return {"reply": "Chưa có phim đã ra mắt phù hợp với khoảng thời gian này. Nếu muốn xem phim tương lai, bạn hãy yêu cầu phim sắp chiếu nhé.", "movies": []}
        if prefs.max_runtime:
            params["with_runtime.lte"] = prefs.max_runtime
            params["with_runtime.gte"] = prefs.min_runtime or 1
        elif prefs.min_runtime:
            params["with_runtime.gte"] = prefs.min_runtime
        if prefs.language:
            params["with_original_language"] = prefs.language
        if args.min_rating is not None:
            params["vote_average.gte"] = args.min_rating
        params.update(self.discovery_filters)
        keyword_ids = []
        for keyword in args.with_keywords:
            if len(keyword) > 80:
                raise ValueError("Từ khóa quá dài.")
            matches = tmdb_get("search/keyword", query=keyword, language="en-US").get("results", [])
            exact = [k for k in matches if normalize(k.get("name", "")) == normalize(keyword)]
            if not exact:
                return {"reply": f"Mình chưa xác định được từ khóa nội dung ‘{keyword}’ trong TMDB. Bạn mô tả cụ thể hơn nhé.", "movies": []}
            keyword_ids.append(str(exact[0]["id"]))
        if keyword_ids:
            params["with_keywords"] = "|".join(keyword_ids)
        rows = tmdb_get("discover/movie", **params).get("results", [])[:20]
        if wants_more(self.message):
            rows = [r for r in rows if r.get("id") not in self.state.shown_ids]
            if len(rows) < 5:
                rows += [r for r in tmdb_get("discover/movie", **params, page=2).get("results", [])[:20]
                         if r.get("id") not in self.state.shown_ids]
        summary = describe_preferences(prefs)
        if args.min_rating is not None:
            summary += ("; " if summary else "") + f"điểm TMDB từ {args.min_rating:g}/10"
        if args.with_keywords:
            summary += ("; " if summary else "") + "chủ đề " + ", ".join(args.with_keywords)
        reply = "Mình tìm theo " + summary + "." if summary else "Đây là các phim mình vừa tìm được trong kho TMDB."
        reply += " Sắp theo điểm đánh giá." if prefs.sort_by == "rating" else " Sắp theo ngày phát hành mới nhất."
        reply += " Chỉ lấy phim sắp chiếu." if prefs.release_scope == "upcoming" else " Chỉ lấy phim đã ra mắt."
        return self.finish_rows(rows, reply, minimum_votes=50 if prefs.sort_by == "rating" else 0)

    def search_movies_by_people(self, args):
        names, people_ids, credit_sets, notes = [], [], [], []
        credit_rows = {}
        for name in dict.fromkeys(n.strip() for n in args.person_names):
            people = [p for p in tmdb_get("search/person", query=name, include_adult="false").get("results", []) if not p.get("adult")]
            exact = [p for p in people if normalize(p.get("name", "")) == normalize(name)]
            people = exact or people
            if not people:
                return {"reply": f"Mình chưa tìm thấy người tên ‘{name}’. Bạn kiểm tra lại tên nhé.", "movies": []}
            was_ambiguous = len(people) > 1
            if was_ambiguous:
                department = "Acting" if args.role == "actor" else "Directing"
                matching_role = [p for p in people if p.get("known_for_department") == department]
                people = matching_role or people
                if args.known_for_movie:
                    hint = normalize(args.known_for_movie)
                    matching_film = [p for p in people if any(
                        hint in {normalize(m.get("title", "")), normalize(m.get("original_title", ""))}
                        for m in p.get("known_for", []))]
                    if not matching_film:
                        hint_rows = tmdb_get("search/movie", query=args.known_for_movie, include_adult="false").get("results", [])
                        hint_ids = {m["id"] for m in hint_rows if m.get("id") and not m.get("adult")}
                        for person in people[:5]:
                            credits = tmdb_get(f"person/{person['id']}/movie_credits")
                            ids = {m["id"] for m in credits.get("cast" if args.role == "actor" else "crew", [])
                                   if m.get("id") and (args.role == "actor" or m.get("job") == "Director")}
                            if ids & hint_ids:
                                matching_film.append(person)
                    people = matching_film
                elif len(people) > 1:
                    ranked = sorted(people, key=lambda p: p.get("popularity", 0), reverse=True)
                    if ranked[0].get("known_for") and ranked[0].get("popularity", 0) >= 1 and ranked[0].get("popularity", 0) >= 5 * max(0.1, ranked[1].get("popularity", 0)):
                        people = ranked[:1]
            if len(people) != 1:
                return {"reply": f"Chưa xác định được đúng {'diễn viên' if args.role == 'actor' else 'đạo diễn'} ‘{name}’. Có người trùng tên; bạn cho mình một phim họ từng tham gia để phân biệt nhé.", "movies": []}
            person = people[0]
            if str(person["id"]) in people_ids:
                continue
            if was_ambiguous and person.get("known_for"):
                known = next((m.get("title") for m in person["known_for"] if m.get("title")), None)
                if known:
                    notes.append(f"Mình dùng hồ sơ {person['name']} được biết đến qua {known}.")
            names.append(person["name"])
            people_ids.append(str(person["id"]))
            credits = tmdb_get(f"person/{person['id']}/movie_credits").get("cast" if args.role == "actor" else "crew", [])
            matches = [r for r in credits if r.get("id") and not r.get("adult") and
                       (args.role == "actor" or r.get("job") == "Director")]
            credit_sets.append({r["id"] for r in matches})
            for row in matches:
                credit_rows.setdefault(row["id"], row)
        common = set.intersection(*credit_sets) if credit_sets else set()
        result = self.finish_rows([row for mid, row in credit_rows.items() if mid in common],
                                 "Chưa tìm được phim phù hợp cho những người bạn yêu cầu.",
                                 minimum_votes=20 if self.state.preferences.sort_by == "rating" else 0)
        together = " cùng tham gia" if len(names) > 1 else " tham gia"
        reason = ("Có " + ", ".join(names) + together + " diễn xuất theo TMDB."
                  if args.role == "actor" else "Do " + ", ".join(names) + " đạo diễn, theo thông tin TMDB.")
        if result["movies"]:
            result["reply"] = " ".join(notes + ["Mình tìm được các phim: " + reason])
            result["reply"] += " Sắp theo điểm đánh giá." if self.state.preferences.sort_by == "rating" else " Sắp theo ngày phát hành mới nhất."
            for card in result["movies"]:
                card["reason"] = reason
        return result

    def search_movie_by_title(self, args):
        rows = tmdb_get("search/movie", query=args.query, include_adult="false").get("results", [])[:20]
        return self.finish_rows(rows, f"Mình tìm được các phim khớp tên ‘{args.query}’ trên TMDB.")

    def get_similar_and_recommended_movies(self, args):
        source, question = self.resolve_movie(args, "get_similar_and_recommended_movies")
        if question:
            return question
        prefs = self.state.preferences
        prefs.reference_title = source.original_title or source.title
        prefs.reference_movie_id = source.tmdb_id
        prefs.reference_year = source.release_date.year if source.release_date else None
        payload = ChatIn(message=self.message, context=prefs)
        stmt = filtered_query(prefs, self.user_id, self.cutoff)
        if wants_more(self.message) and self.state.shown_ids:
            stmt = stmt.where(Movie.tmdb_id.not_in(self.state.shown_ids))
        if self.min_rating is not None:
            stmt = stmt.where(Movie.tmdb_rating >= self.min_rating)
        movies, result = recommend_similar(self.db, prefs, payload, stmt, remote_only=True)
        if result.get("catalog_source") == "cached" and not movies:
            return {"reply": "TMDB đang không phản hồi đầy đủ nên mình chưa thể xác thực phim tương tự. Bạn thử lại sau nhé.", "movies": []}
        if result.get("reference_candidates"):
            return self.choose_movie(result["reference_candidates"], "get_similar_and_recommended_movies", args)
        self.state.pending = {}
        return {"reply": result["reply"], "movies": [
            {**snapshot(m), "reason": result.get("_reasons", {}).get(m.tmdb_id) or reason_for(m, prefs)} for m in movies
        ]}

    def choose_movie(self, choices, tool_name, args):
        self.state.pending = {c["tmdb_id"]: c for c in choices}
        self.state.pending_action = {"tool": tool_name, "arguments": args.model_dump()}
        cards = [{**snapshot(self.db.get(Movie, mid)),
                  "reason": choice["overview"] or "Bạn chọn đúng phiên bản phim muốn tra cứu nhé."}
                 for mid, choice in self.state.pending.items()]
        return {"reply": "Có nhiều phim khớp tên này. Bạn chọn đúng phim bên dưới hoặc cho mình năm phát hành nhé.",
                "movies": cards, "action": "choose-reference"}

    def resolve_movie(self, args, tool_name):
        title, annotated_year = split_title_year(args.movie_title)
        year = args.year or annotated_year
        selected = self.state.selected_titles.get(normalize(title))
        selected_id = selected["id"] if selected and (not year or selected["year"] == year) else None
        prefs = Preferences(reference_title=title, reference_year=year, reference_movie_id=selected_id)
        movie, question, failed, choices = resolve_reference(self.db, prefs, remote_only=True)
        if choices:
            return None, self.choose_movie(choices, tool_name, args)
        if question:
            reply = "TMDB chưa phản hồi, bạn thử lại sau nhé." if failed else f"Mình chưa tìm được phim ‘{title}’. Bạn kiểm tra tên gốc và năm phát hành nhé."
            return None, {"reply": reply, "movies": []}
        self.state.pending.clear()
        self.state.pending_action.clear()
        self.state.selected_titles[normalize(title)] = {"id": movie.tmdb_id, "year": movie.release_date.year if movie.release_date else None}
        self.state.selected_titles = dict(list(self.state.selected_titles.items())[-16:])
        return movie, None

    def get_trending_or_cinema_movies(self, args):
        if args.category == "trending":
            data = tmdb_get(f"trending/movie/{args.time_window}")
            reply = "Các phim đang thịnh hành " + ("hôm nay" if args.time_window == "day" else "trong tuần") + " trên TMDB."
        else:
            data = tmdb_get(f"movie/{args.category}", region=args.region)
            labels = {"now_playing": "đang chiếu", "upcoming": "sắp chiếu", "top_rated": "có điểm đánh giá cao"}
            reply = f"Các phim {labels[args.category]} theo TMDB" + (f" tại {args.region}." if args.category != "top_rated" else ".")
        return self.finish_rows(data.get("results", [])[:20], reply)

    def movie_details(self, movie):
        detail = tmdb_get(f"movie/{movie.tmdb_id}", append_to_response="credits,videos,release_dates")
        if not detail.get("overview"):
            try:
                english = tmdb_get(f"movie/{movie.tmdb_id}", language="en-US")
                if english.get("overview"):
                    detail = {**detail, "overview": english["overview"], "_overview_language": "en"}
            except HTTPException:
                pass
        videos = detail.get("videos", {}).get("results", [])
        trailer = official_trailer(detail)
        if not trailer:
            try:
                fallback = tmdb_get(f"movie/{movie.tmdb_id}/videos", language="en-US")
                videos = videos + fallback.get("results", [])
                trailer = official_trailer({"videos": fallback})
            except HTTPException:
                pass
        # Keep the existing detail modal consistent with the verified chat link.
        verified = [v for v in videos if trailer and v.get("key") == trailer.rsplit("=", 1)[-1]]
        save_movies(self.db, [{**detail, "videos": {"results": verified[:1]}}], details=True)
        movie = self.db.get(Movie, movie.tmdb_id)
        return movie, detail, trailer

    def get_movie_full_details(self, args):
        movie, question = self.resolve_movie(args, "get_movie_full_details")
        if question:
            return question
        movie, detail, trailer = self.movie_details(movie)
        reply = full_details_text(movie, detail, args.region)
        reply += "\nCó trailer YouTube chính thức bên dưới." if trailer else "\nTMDB chưa cung cấp trailer YouTube chính thức có thể xác minh."
        return {"reply": reply, "movies": [{**snapshot(movie), "trailer_url": trailer,
                 "reason": "Thông tin, dàn diễn viên và trailer được đối chiếu từ dữ liệu TMDB."}]}

    def get_movie_watch_providers(self, args):
        movie, question = self.resolve_movie(args, "get_movie_watch_providers")
        if question:
            return question
        data = tmdb_get(f"movie/{movie.tmdb_id}/watch/providers")
        country = data.get("results", {}).get(args.country_code, {})
        labels = {"flatrate": "Thuê bao", "free": "Miễn phí", "ads": "Có quảng cáo", "rent": "Thuê lẻ", "buy": "Mua"}
        lines = [label + ": " + ", ".join(dict.fromkeys(p["provider_name"] for p in country.get(key, []) if p.get("provider_name")))
                 for key, label in labels.items() if any(p.get("provider_name") for p in country.get(key, []))]
        reply = (f"Nơi xem {movie.title} tại {args.country_code}:\n" + "\n".join(lines) if lines else
                 f"TMDB/JustWatch chưa có dữ liệu nơi xem {movie.title} tại {args.country_code}; mình chưa thể xác nhận nền tảng nào.")
        reply += "\nNguồn dữ liệu nơi xem: TMDB/JustWatch."
        return {"reply": reply, "movies": [{**snapshot(movie), "reason": f"Tra cứu nơi xem tại {args.country_code} từ TMDB/JustWatch."}]}
