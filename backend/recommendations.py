import re
import unicodedata

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .ai import parse_preferences, resolve_provider
from .models import Movie, Watchlist
from .queries import has_any_genre
from .schemas import ChatIn, Preferences
from .tmdb import GENRES, save_movies, tmdb_get


def normalize(value: str):
    return "".join(
        c
        for c in unicodedata.normalize("NFD", value.lower().replace("đ", "d"))
        if unicodedata.category(c) != "Mn"
    )


def rules_preferences(payload: ChatIn) -> Preferences:
    text = normalize(
        " ".join(
            [t.content for t in payload.history if t.role == "user"] + [payload.message]
        )
    )
    genres = {
        28: ["hanh dong", "action"],
        35: ["hai", "vui ve", "vui nhon", "nhe nhang"],
        27: ["kinh di", "horror"],
        9648: ["trinh tham", "bi an", "twist"],
        10749: ["lang man", "tinh cam"],
        878: ["vien tuong", "sci-fi", "sci fi"],
        16: ["hoat hinh", "anime"],
        18: ["chinh kich", "cam dong"],
        10751: ["gia dinh"],
        10752: ["chien tranh"],
    }
    wanted, excluded = [], []
    for genre_id, terms in genres.items():
        for term in terms:
            pattern = r"\b" + re.escape(term) + r"\b"
            if re.search(pattern, text):
                if re.search(
                    r"(khong(?: thich| muon)?|dung|tranh|bo|khong co)\s+(?:phim\s+)?"
                    + pattern,
                    text,
                ):
                    excluded.append(genre_id)
                else:
                    wanted.append(genre_id)
                break
    minutes = list(
        re.finditer(r"(?:duoi|toi da|khong qua|<)\s*(\d+)\s*(phut|tieng|gio)", text)
    )
    max_runtime = None
    if minutes:
        match = minutes[-1]
        max_runtime = int(match[1]) * (1 if match[2] == "phut" else 60)
        max_runtime = min(600, max(1, max_runtime))
    language = None
    for term, code in [
        ("phim han", "ko"),
        ("han quoc", "ko"),
        ("phim nhat", "ja"),
        ("nhat ban", "ja"),
        ("phim viet", "vi"),
        ("viet nam", "vi"),
        ("phim phap", "fr"),
        ("phim an do", "hi"),
    ]:
        if term in text:
            language = code
    years = re.search(r"(?:tu nam|sau nam|tu)\s*((?:19|20)\d{2})", text)
    return Preferences(
        genre_ids=list(dict.fromkeys(wanted))[:5],
        excluded_genre_ids=list(dict.fromkeys(excluded))[:5],
        max_runtime=max_runtime,
        min_year=int(years[1]) if years else None,
        language=language,
    )


def get_preferences(payload: ChatIn):
    provider = resolve_provider(payload.provider)
    if provider == "rules":
        return rules_preferences(payload), "rules", None
    try:
        return parse_preferences(payload, provider), provider, None
    except (
        httpx.HTTPError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
    ):
        notice = (
            "Qwen local chưa sẵn sàng hoặc trả dữ liệu không hợp lệ. Hãy mở Ollama và tải "
            + get_settings().ollama_model
            + ". Đang dùng bộ lọc từ khóa."
            if provider == "ollama"
            else "Gemini chưa có key, bị lỗi hoặc trả dữ liệu không hợp lệ. Đang dùng bộ lọc từ khóa."
        )
        return rules_preferences(payload), "rules_fallback", notice


def recommend(db: Session, payload: ChatIn, user_id: int | None):
    prefs, mode, notice = get_preferences(payload)
    remote_failed = False
    if get_settings().tmdb_access_token:
        params = {
            "sort_by": "vote_average.desc",
            "vote_count.gte": 100,
            "include_adult": "false",
        }
        if prefs.genre_ids:
            params["with_genres"] = "|".join(map(str, prefs.genre_ids))
        if prefs.excluded_genre_ids:
            params["without_genres"] = ",".join(map(str, prefs.excluded_genre_ids))
        if prefs.max_runtime:
            params["with_runtime.lte"] = prefs.max_runtime
            params["with_runtime.gte"] = 1
        if prefs.min_year:
            params["primary_release_date.gte"] = f"{prefs.min_year}-01-01"
        if prefs.max_year:
            params["primary_release_date.lte"] = f"{prefs.max_year}-12-31"
        if prefs.language:
            params["with_original_language"] = prefs.language
        try:
            data = tmdb_get("discover/movie", **params)
            # Discover doesn't return runtime. Fetch candidate details before enforcing it.
            rows = data.get("results", [])[:8]
            save_movies(db, rows)
            if prefs.max_runtime:
                for row in rows:
                    movie = db.get(Movie, row["id"])
                    if movie and movie.runtime is None:
                        detail = tmdb_get(
                            f"movie/{row['id']}", append_to_response="credits,videos"
                        )
                        save_movies(db, [detail], details=True)
        except HTTPException:
            remote_failed = True
    stmt = select(Movie)
    if prefs.genre_ids:
        stmt = stmt.where(has_any_genre(prefs.genre_ids))
    if prefs.excluded_genre_ids:
        stmt = stmt.where(~has_any_genre(prefs.excluded_genre_ids))
    if prefs.max_runtime:
        stmt = stmt.where(Movie.runtime > 0, Movie.runtime <= prefs.max_runtime)
    if prefs.min_year:
        stmt = stmt.where(Movie.release_date >= f"{prefs.min_year}-01-01")
    if prefs.max_year:
        stmt = stmt.where(Movie.release_date <= f"{prefs.max_year}-12-31")
    if prefs.language:
        stmt = stmt.where(Movie.original_language == prefs.language)
    if user_id:
        watched = select(Watchlist.movie_tmdb_id).where(
            Watchlist.user_id == user_id, Watchlist.status == "watched"
        )
        stmt = stmt.where(Movie.tmdb_id.not_in(watched))
    movies = db.scalars(
        stmt.order_by(Movie.tmdb_rating.desc(), Movie.popularity.desc()).limit(5)
    ).all()
    reply = (
        prefs.intro
        if mode in {"gemini", "ollama"}
        else "Mình lọc theo yêu cầu của bạn và ưu tiên các phim có điểm TMDB cao."
    )
    if not movies:
        reply = "Chưa tìm thấy phim phù hợp trong danh mục hiện có. Bạn thử bỏ bớt điều kiện hoặc chọn thể loại khác nhé."
    return movies, {
        "reply": reply,
        "mode": mode,
        "provider_notice": notice,
        "model": get_settings().ollama_model
        if mode == "ollama"
        else get_settings().gemini_model
        if mode == "gemini"
        else None,
        "preferences": prefs.model_dump(exclude={"intro"}),
        "catalog_source": "cached"
        if remote_failed
        else ("tmdb" if get_settings().tmdb_access_token else "local"),
    }
