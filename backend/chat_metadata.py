"""Human-readable TMDB lookups and verified metadata formatting."""

import re

from .preference_rules import GENRE_TERMS, normalize
from .tmdb import GENRES


ENGLISH_GENRES = {
    28: "action", 12: "adventure", 16: "animation", 35: "comedy", 80: "crime",
    99: "documentary", 18: "drama", 10751: "family", 14: "fantasy", 36: "history",
    27: "horror", 10402: "music", 9648: "mystery", 10749: "romance",
    878: "science fiction", 10770: "tv movie", 53: "thriller", 10752: "war", 37: "western",
}
GENRE_NAMES = {normalize(name): gid for gid, name in GENRES.items()}
GENRE_NAMES.update({name: gid for gid, name in ENGLISH_GENRES.items()})
GENRE_NAMES.update({term: gid for gid, terms in GENRE_TERMS.items() for term in terms})

KEYWORD_TRANSLATIONS = {
    "chua lanh": "healing", "du hanh thoi gian": "time travel",
    "vong lap thoi gian": "time loop", "tinh ban": "friendship", "tra thu": "revenge",
    "bao thu": "revenge", "sinh ton": "survival", "dieu uoc": "wish",
    "am anh": "obsession", "tinh yeu don phuong": "unrequited love",
    "cuop ngan hang": "bank robbery", "ngoai hanh tinh": "alien",
}


def genre_ids(names):
    result = []
    for name in names:
        key = re.sub(r"^phim\s+", "", normalize(name).strip())
        if key not in GENRE_NAMES:
            raise ValueError(f"Chưa nhận diện được thể loại ‘{name}’.")
        if GENRE_NAMES[key] not in result:
            result.append(GENRE_NAMES[key])
    return result


def english_keywords(text):
    values = re.split(r"[,;]", text)
    result = []
    for value in values:
        value = value.strip()
        if not value:
            continue
        value = KEYWORD_TRANSLATIONS.get(normalize(value), value)
        if value.isdigit() or len(value) > 80 or len(result) >= 5:
            raise ValueError("Hãy dùng tối đa 5 tên từ khóa nội dung, không dùng ID.")
        result.append(value)
    return list(dict.fromkeys(result))


def official_trailer(detail):
    videos = [v for v in detail.get("videos", {}).get("results", [])
              if v.get("site") == "YouTube" and v.get("type") == "Trailer"
              and v.get("official") is True and isinstance(v.get("key"), str)
              and re.fullmatch(r"[A-Za-z0-9_-]{11}", v["key"])]
    if not videos:
        return None
    videos.sort(key=lambda v: (v.get("iso_639_1") == "vi", v.get("published_at", "")), reverse=True)
    return "https://www.youtube.com/watch?v=" + videos[0]["key"]


def certification(detail, region):
    countries = detail.get("release_dates", {}).get("results", [])
    for code in dict.fromkeys([region, "US"]):
        releases = [r for country in countries if country.get("iso_3166_1") == code
                    for r in country.get("release_dates", []) if r.get("certification")]
        releases.sort(key=lambda r: (r.get("type") != 3, r.get("type", 99)))
        if releases:
            suffix = f"; TMDB chưa có phân loại cho {region}" if code != region else ""
            return f"{releases[0]['certification']} ({code}{suffix})"
    return f"TMDB chưa có dữ liệu cho {region}"


def full_details_text(movie, detail, region):
    credits = detail.get("credits", {})
    directors = list(dict.fromkeys(p["name"] for p in credits.get("crew", [])
                                  if p.get("job") == "Director" and p.get("name")))
    cast = [p["name"] for p in credits.get("cast", [])[:5] if p.get("name")]
    runtime = f"{movie.runtime} phút" if movie.runtime else "TMDB chưa có thời lượng"
    return (
        f"{movie.title}: {runtime}.\n"
        + "Đạo diễn: " + (", ".join(directors) or "TMDB chưa có dữ liệu") + ".\n"
        + "Diễn viên chính: " + (", ".join(cast) or "TMDB chưa có dữ liệu") + ".\n"
        + "Phân loại độ tuổi: " + certification(detail, region) + ".\n"
        + ("Nội dung theo TMDB (tiếng Anh): " if detail.get("_overview_language") == "en" else "Nội dung theo TMDB: ")
        + (movie.overview[:1200] or "Chưa có mô tả.")
    )
