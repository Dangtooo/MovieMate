import re
from datetime import timedelta

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .ai import parse_preferences, resolve_provider
from .models import Movie, Watchlist
from .queries import has_any_genre
from .schemas import ChatIn
from .preference_rules import normalize, rules_preferences, describe_preferences, wants_more, requested_language
from .similarity import recommend_similar
from .tmdb import GENRES, save_movies, tmdb_get
from .query_policy import today


def get_preferences(payload: ChatIn):
    provider = resolve_provider(payload.provider)
    if provider == "rules":
        return rules_preferences(payload), "rules", None
    try:
        preferences = parse_preferences(payload, provider)
        policy = rules_preferences(payload)
        preferences.sort_by, preferences.release_scope = policy.sort_by, policy.release_scope
        explicit_language, language = requested_language(payload.message)
        if explicit_language:
            preferences.language = language
        return preferences, provider, None
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
    cutoff = today()
    text = normalize(payload.message).strip(" .!?✦")
    conversational_reply = None
    if text in {"chao", "xin chao", "hello", "hi", "alo", "chao ban", "hey"}:
        conversational_reply = "Chào bạn! Bạn thích thể loại nào, ngôn ngữ gì hoặc có bao nhiêu thời gian xem phim? Ví dụ: hoạt hình Nhật dưới 2 tiếng."
    elif text in {"cam on", "cam on ban", "thanks", "thank you", "ok", "oke", "okay"}:
        conversational_reply = "Rất vui được giúp bạn! Bạn có thể hỏi phim khác hoặc đổi thể loại, thời lượng hay năm phát hành."
    if conversational_reply:
        prefs = rules_preferences(payload)
        return [], {
            "reply": conversational_reply, "mode": "rules", "model": None,
            "provider_notice": None, "preferences": prefs.model_dump(exclude={"intro"}),
            "catalog_source": "local",
        }
    prefs, mode, notice = get_preferences(payload)
    # Preserve an explicitly named reference even if a model drops/mistranslates it.
    explicit = rules_preferences(payload)
    if explicit.reference_title:
        prefs.reference_title = explicit.reference_title
        prefs.reference_year = explicit.reference_year
        prefs.reference_movie_id = explicit.reference_movie_id
    # Never issue a contradictory query, even when a model returns valid JSON.
    prefs.genre_ids = list(dict.fromkeys(g for g in prefs.genre_ids if g in GENRES and g not in prefs.excluded_genre_ids))
    prefs.excluded_genre_ids = list(dict.fromkeys(g for g in prefs.excluded_genre_ids if g in GENRES))
    summary = describe_preferences(prefs)
    more = wants_more(payload.message)
    response = {
        "mode": mode,
        "provider_notice": notice,
        "model": get_settings().ollama_model if mode == "ollama" else get_settings().gemini_model if mode == "gemini" else None,
        "preferences": prefs.model_dump(exclude={"intro"}),
        "catalog_source": "local",
    }
    if (prefs.min_year and prefs.max_year and prefs.min_year > prefs.max_year) or (
        prefs.min_runtime and prefs.max_runtime and prefs.min_runtime > prefs.max_runtime
    ):
        return [], {**response, "reply": "Khoảng thời gian đang mâu thuẫn: " + summary + ". Bạn cho mình khoảng bắt đầu và kết thúc đúng nhé?"}
    if not summary and not prefs.reference_title and mode in {"rules", "rules_fallback"} and not more and not re.search(
        r"\b(phim|goi y|de xuat|recommend|xem gi|bat dau lai)\b", text
    ):
        return [], {**response, "reply": "Mình chưa hiểu tiêu chí chọn phim trong câu này. Bạn nói rõ thể loại, ngôn ngữ hoặc thời lượng nhé; ví dụ: phim hài dưới 90 phút."}
    remote_failed = False
    if get_settings().tmdb_access_token and not prefs.reference_title:
        params = {
            "sort_by": "vote_average.desc" if prefs.sort_by == "rating" else "primary_release_date.desc",
            "include_adult": "false",
        }
        if prefs.sort_by == "rating":
            params["vote_count.gte"] = 50
        if prefs.genre_ids:
            params["with_genres"] = "|".join(map(str, prefs.genre_ids))
        if prefs.excluded_genre_ids:
            params["without_genres"] = ",".join(map(str, prefs.excluded_genre_ids))
        if prefs.max_runtime:
            params["with_runtime.lte"] = prefs.max_runtime
            params["with_runtime.gte"] = 1
        if prefs.min_runtime:
            params["with_runtime.gte"] = prefs.min_runtime
        if prefs.min_year:
            params["primary_release_date.gte"] = f"{prefs.min_year}-01-01"
        if prefs.max_year:
            params["primary_release_date.lte"] = f"{prefs.max_year}-12-31"
        if prefs.release_scope == "upcoming":
            params["primary_release_date.gte"] = max(params.get("primary_release_date.gte", ""), (cutoff + timedelta(days=1)).isoformat())
        else:
            params["primary_release_date.lte"] = min(params.get("primary_release_date.lte", cutoff.isoformat()), cutoff.isoformat())
        if prefs.language:
            params["with_original_language"] = prefs.language
        try:
            valid_range = params.get("primary_release_date.gte", "") <= params.get("primary_release_date.lte", "9999-12-31")
            data = tmdb_get("discover/movie", **params) if valid_range else {"results": []}
            # Discover doesn't return runtime. Fetch candidate details before enforcing it.
            rows = data.get("results", [])[:8]
            save_movies(db, rows)
            if prefs.max_runtime or prefs.min_runtime:
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
    stmt = stmt.where(Movie.release_date > cutoff) if prefs.release_scope == "upcoming" else stmt.where(Movie.release_date <= cutoff)
    if prefs.genre_ids:
        stmt = stmt.where(has_any_genre(prefs.genre_ids))
    if prefs.excluded_genre_ids:
        stmt = stmt.where(~has_any_genre(prefs.excluded_genre_ids))
    if prefs.max_runtime and not prefs.reference_title:
        stmt = stmt.where(Movie.runtime > 0, Movie.runtime <= prefs.max_runtime)
    if prefs.min_runtime and not prefs.reference_title:
        stmt = stmt.where(Movie.runtime >= prefs.min_runtime)
    if prefs.min_year:
        stmt = stmt.where(Movie.release_date >= f"{prefs.min_year}-01-01")
    if prefs.max_year:
        stmt = stmt.where(Movie.release_date <= f"{prefs.max_year}-12-31")
    if prefs.language:
        stmt = stmt.where(Movie.original_language.in_(prefs.language.split("|")))
    if more and payload.shown_movie_ids:
        stmt = stmt.where(Movie.tmdb_id.not_in(payload.shown_movie_ids))
    if user_id:
        watched = select(Watchlist.movie_tmdb_id).where(
            Watchlist.user_id == user_id, Watchlist.status == "watched"
        )
        stmt = stmt.where(Movie.tmdb_id.not_in(watched))
    if prefs.reference_title:
        movies, similarity = recommend_similar(db, prefs, payload, stmt)
        return movies, {
            **response, **similarity,
            "preferences": prefs.model_dump(exclude={"intro"}),
        }
    ordering = (Movie.tmdb_rating.desc(), Movie.release_date.desc()) if prefs.sort_by == "rating" else (Movie.release_date.desc(),)
    movies = db.scalars(stmt.order_by(*ordering, Movie.tmdb_id).limit(5)).all()
    # Describe validated criteria rather than displaying unverified model prose.
    reply = "Mình tìm theo: " + summary + "." if summary else "Mình sắp theo " + ("điểm đánh giá." if prefs.sort_by == "rating" else "ngày phát hành mới nhất.")
    if more:
        reply += " Đã bỏ qua các phim vừa gợi ý."
    if not movies:
        reply = "Chưa tìm thấy " + ("phim khác" if more else "phim") + " phù hợp trong danh mục hiện có."
        if summary:
            reply += " Tiêu chí đang dùng: " + summary + "."
        reply += " Bạn có thể nói 'bỏ giới hạn thời lượng', 'nước nào cũng được' hoặc đổi thể loại."
    if not get_settings().tmdb_access_token:
        reply += " Mình đang tìm trong danh mục lưu trên máy; chưa kết nối kho TMDB."
    return movies, {
        **response,
        "reply": reply,
        "catalog_source": "cached"
        if remote_failed
        else ("tmdb" if get_settings().tmdb_access_token else "local"),
    }
