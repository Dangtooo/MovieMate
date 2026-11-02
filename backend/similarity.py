"""Movie-to-movie matching using verified plots, keywords and related titles.

Ratings only break ties. Genre overlap by itself is not evidence of a similar plot.
No model-generated movie names or invented plot descriptions enter the results.
"""

import math
import re
from datetime import date
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Movie
from .preference_rules import normalize, wants_more
from .tmdb import GENRES, save_movies, tmdb_get


# These labels describe explicit words in metadata; they are not inferred reviews.
THEMES = {
    "ám ảnh": ["am anh", "obsession", "obsessive"],
    "theo dõi": ["theo doi", "stalking", "stalker"],
    "siêu nhiên": ["sieu nhien", "supernatural", "demonic", "demon"],
    "điều ước": ["dieu uoc", "wish", "wishes"],
    "tình yêu": ["tinh yeu", "romantic", "romance", "love"],
    "điều tra": ["dieu tra", "investigation", "detective"],
    "trả thù": ["tra thu", "revenge", "vengeance"],
    "mất tích": ["mat tich", "missing", "disappearance"],
    "sinh tồn": ["sinh ton", "survival", "survive"],
    "du hành thời gian": ["du hanh thoi gian", "time travel", "time loop"],
    "ngoài hành tinh": ["ngoai hanh tinh", "alien", "extraterrestrial"],
    "gia đình": ["gia dinh", "family"],
    "tội phạm": ["toi pham", "crime", "criminal"],
}
STOP_WORDS = set("a an the of to in on and or is are was with for from his her their this that as by at into who when mot nhung cac va la cua cho trong voi tu den duoc khi nguoi nhan vat cau chuyen ve bo phim anh co nay do sau cung de da thi bi khong phai se hon".split())
BROAD_THEMES = {"gia đình", "tình yêu", "tội phạm", "siêu nhiên"}
NARRATIVE_ANCHORS = {"siêu nhiên", "điều ước", "du hành thời gian", "ngoài hành tinh"}
GENERIC_KEYWORDS = {"love", "family", "crime", "romance", "supernatural", "supernatural horror",
                    "horrified", "depressing", "distressing", "frightened", "admiring", "excited"}


def themes(text):
    text = normalize(text)
    return {label for label, terms in THEMES.items() if any(
        re.search(r"\b" + re.escape(term) + r"\b", text) for term in terms
    )}


def features(text):
    words = [w for w in re.findall(r"\b\w+\b", normalize(text)) if w not in STOP_WORDS and len(w) > 1]
    return Counter(words + [a + " " + b for a, b in zip(words, words[1:])])


def keyword_names(detail):
    return {k["name"].lower() for k in detail.get("keywords", {}).get("keywords", []) if k.get("name")}


def movie_label(movie):
    year = movie.release_date.year if movie.release_date else "chưa rõ năm"
    return f"{movie.title} ({year})"


def resolve_reference(db, prefs, remote_only=False):
    """Return an unambiguous title or a question, never guess a remake/version."""
    remote_failed = False
    remote_ids = None
    if prefs.reference_movie_id:
        chosen = db.get(Movie, prefs.reference_movie_id)
        if chosen:
            return chosen, None, False, []
    if get_settings().tmdb_access_token:
        params = {"query": prefs.reference_title, "include_adult": "false"}
        if prefs.reference_year:
            params["year"] = prefs.reference_year
        try:
            rows = tmdb_get("search/movie", **params).get("results", [])
            remote_ids = [row["id"] for row in rows[:20] if not row.get("adult") and row.get("id")]
            save_movies(db, rows[:20])
        except HTTPException:
            remote_failed = True
    # LIKE special characters are treated literally in user-provided titles.
    query = select(Movie).where(or_(
        Movie.title.icontains(prefs.reference_title, autoescape=True),
        Movie.original_title.icontains(prefs.reference_title, autoescape=True),
    ))
    if remote_only:
        query = query.where(Movie.tmdb_id.in_(remote_ids or []))
    if prefs.reference_year:
        query = query.where(
            Movie.release_date >= f"{prefs.reference_year}-01-01",
            Movie.release_date <= f"{prefs.reference_year}-12-31",
        )
    candidates = list(db.scalars(query.order_by(Movie.release_date.desc(), Movie.popularity.desc(), Movie.tmdb_id).limit(30)))
    exact = [m for m in candidates if normalize(prefs.reference_title) in {
        normalize(m.title), normalize(m.original_title),
    }]
    candidates = exact or candidates
    if not candidates:
        return None, f"Mình chưa tìm được dữ liệu xác thực về phim ‘{prefs.reference_title}’. Bạn cho mình tên gốc và năm phát hành nhé. Mình chưa thể chọn phim tương tự khi chưa xác định được phim gốc.", remote_failed, []
    if len(candidates) > 1:
        options = "; ".join(movie_label(m) for m in candidates[:5])
        choices = [{"tmdb_id": m.tmdb_id, "title": m.title, "original_title": m.original_title,
                    "year": m.release_date.year if m.release_date else None,
                    "overview": m.overview[:220], "poster_path": m.poster_path} for m in candidates[:8]]
        return None, "Có nhiều phim khớp tên này: " + options + ". Bạn chọn đúng phim bên dưới hoặc cho mình năm phát hành nhé.", remote_failed, choices
    return candidates[0], None, remote_failed, []


def recommend_similar(db: Session, prefs, payload, stmt, remote_only=False):
    source, question, remote_failed, choices = resolve_reference(db, prefs, remote_only)
    if question:
        return [], {"reply": question, "catalog_source": "cached" if remote_failed else "tmdb" if get_settings().tmdb_access_token else "local", "reference_movie": None, "reference_candidates": choices, "_reasons": {}}
    prefs.reference_title = source.original_title or source.title
    prefs.reference_movie_id = source.tmdb_id
    prefs.reference_year = source.release_date.year if source.release_date else None
    detail = {}
    related = set()
    candidate_details = {}
    if get_settings().tmdb_access_token:
        try:
            detail = tmdb_get(f"movie/{source.tmdb_id}", append_to_response="keywords,recommendations,similar,credits,videos")
            save_movies(db, [detail], details=True)
            related_rows = {}
            for section in ("recommendations", "similar"):
                for row in detail.get(section, {}).get("results", []):
                    if row.get("id") and not row.get("adult"):
                        related_rows[row["id"]] = row
                if wants_more(payload.message):
                    # Try the next page so repeated requests can progress beyond page one.
                    for row in tmdb_get(f"movie/{source.tmdb_id}/{section}", page=2).get("results", []):
                        if row.get("id") and not row.get("adult"):
                            related_rows[row["id"]] = row
            # Related lists can be broad. Expand using distinctive plot themes,
            # e.g. wishes/obsession rather than every supernatural thriller.
            keyword_rows = detail.get("keywords", {}).get("keywords", [])
            anchor_keywords = [k["id"] for k in keyword_rows if k.get("id") and
                               themes(k.get("name", "")) & (NARRATIVE_ANCHORS - {"siêu nhiên"})]
            distinctive = anchor_keywords or [k["id"] for k in keyword_rows
                                               if k.get("id") and themes(k.get("name", "")) - BROAD_THEMES]
            distinctive = distinctive[:5]
            if distinctive:
                params = {"with_keywords": "|".join(map(str, distinctive)), "include_adult": "false",
                          "sort_by": "popularity.desc", "vote_count.gte": 20}
                if prefs.genre_ids or source.genre_ids:
                    params["with_genres"] = "|".join(map(str, prefs.genre_ids or source.genre_ids))
                for row in tmdb_get("discover/movie", **params).get("results", [])[:20]:
                    if row.get("id") and not row.get("adult"):
                        related_rows[row["id"]] = row
            related = set(related_rows)
            save_movies(db, list(related_rows.values()))
        except HTTPException:
            remote_failed = True
    # Apply every user constraint and watched exclusion BEFORE ranking candidates.
    if remote_only:
        stmt = stmt.where(Movie.tmdb_id.in_(related))
    eligible = list(db.scalars(stmt.where(Movie.tmdb_id != source.tmdb_id).order_by(
        Movie.tmdb_id.in_(related).desc(), Movie.tmdb_id,
    ).limit(1000)))
    source = db.get(Movie, source.tmdb_id)
    source_keywords = keyword_names(detail)
    source_text = source.overview + " " + " ".join(source_keywords)
    source_themes = themes(source_text)
    source_anchors = source_themes & NARRATIVE_ANCHORS
    source_genres = set(source.genre_ids or [])
    if not source.overview.strip() and not source_keywords:
        return [], {"reply": f"Đã tìm thấy {movie_label(source)}, nhưng chưa có mô tả nội dung để so sánh đáng tin cậy. Mình cần thêm dữ liệu phim gốc trước khi gợi ý.", "catalog_source": "cached" if remote_failed else "local", "reference_movie": None, "_reasons": {}}
    # Bound detail requests; favour TMDB-related candidates, then plot overlap.
    source_features = set(features(source_text))
    eligible.sort(key=lambda m: (
        m.tmdb_id in related,
        bool(source_anchors & themes(m.overview)),
        len(source_themes & themes(m.overview)) + len(source_features & set(features(m.overview))) / 20,
    ), reverse=True)
    pool = eligible[:80]
    if get_settings().tmdb_access_token and not remote_failed:
        # Fetch keywords and missing runtimes for a small candidate pool.
        # Unknown runtimes are handled below, before the final constraints check.
        def fetch_detail(movie_id):
            try:
                return movie_id, tmdb_get(f"movie/{movie_id}", append_to_response="keywords,credits,videos")
            except HTTPException:
                return movie_id, None
        with ThreadPoolExecutor(max_workers=4) as executor:
            details = list(executor.map(fetch_detail, [m.tmdb_id for m in pool[:8]]))
        for movie_id, item in details:
            if item:
                candidate_details[movie_id] = item
                save_movies(db, [item], details=True)
            else:
                remote_failed = True
        # save_movies expires objects, so read the final constraints again.
        allowed_ids = set(db.scalars(stmt.with_only_columns(Movie.tmdb_id)))
        pool = [m for m in pool if m.tmdb_id in allowed_ids]
    if prefs.max_runtime:
        pool = [m for m in pool if m.runtime and 0 < m.runtime <= prefs.max_runtime]
    if prefs.min_runtime:
        pool = [m for m in pool if m.runtime and m.runtime >= prefs.min_runtime]
    documents = {source.tmdb_id: features(source_text)}
    for movie in pool:
        keywords = keyword_names(candidate_details.get(movie.tmdb_id, {}))
        documents[movie.tmdb_id] = features(movie.overview + " " + " ".join(keywords))
    frequency = Counter(term for doc in documents.values() for term in doc)
    vectors = {mid: {term: count * (math.log((1 + len(documents)) / (1 + frequency[term])) + 1)
                     for term, count in doc.items()} for mid, doc in documents.items()}
    def cosine(left, right):
        norm = math.sqrt(sum(v * v for v in left.values()) * sum(v * v for v in right.values()))
        return sum(v * right.get(k, 0) for k, v in left.items()) / norm if norm else 0
    scored = []
    reasons = {}
    for movie in pool:
        other_keywords = keyword_names(candidate_details.get(movie.tmdb_id, {}))
        shared_keywords = source_keywords & other_keywords
        shared_themes = source_themes & themes(movie.overview + " " + " ".join(other_keywords))
        if source_anchors and not source_anchors & shared_themes:
            continue
        shared_genres = source_genres & set(movie.genre_ids or [])
        genre_score = len(shared_genres) / max(1, len(source_genres | set(movie.genre_ids or [])))
        plot_score = cosine(vectors[source.tmdb_id], vectors[movie.tmdb_id])
        # A common broad genre or a high rating is insufficient on its own.
        specific_themes = shared_themes - BROAD_THEMES
        specific_keywords = shared_keywords - GENERIC_KEYWORDS
        if not (specific_keywords or specific_themes or (plot_score >= 0.16 and shared_genres)):
            continue
        keyword_score = len(specific_keywords) / max(1, len(source_keywords - GENERIC_KEYWORDS))
        def theme_weight(theme):
            return 5 if theme in NARRATIVE_ANCHORS else 1 if theme in BROAD_THEMES else 3
        theme_score = sum(map(theme_weight, shared_themes)) / max(1, sum(map(theme_weight, source_themes)))
        score = 0.35 * keyword_score + 0.25 * plot_score + 0.30 * theme_score + 0.08 * genre_score + 0.02 * (movie.tmdb_id in related)
        bits = []
        if shared_themes:
            bits.append("Cùng đề cập: " + ", ".join(sorted(shared_themes)[:3]))
        if specific_keywords:
            bits.append("Từ khóa chung: " + ", ".join(sorted(specific_keywords)[:3]))
        if shared_genres:
            bits.append("Chung thể loại " + ", ".join(GENRES[g] for g in sorted(shared_genres) if g in GENRES))
        if not shared_themes and not shared_keywords:
            bits.insert(0, "Có điểm gần nhau trong mô tả nội dung")
        reasons[movie.tmdb_id] = " · ".join(bits)
        scored.append((score, movie.tmdb_rating or 0, -movie.tmdb_id, movie))
    scored.sort(key=lambda row: row[:3], reverse=True)
    movies = [row[3] for row in scored[:5]]
    ordering = (lambda m: (m.tmdb_rating or 0, m.release_date or date.min)) if prefs.sort_by == "rating" else (lambda m: m.release_date or date.min)
    movies.sort(key=ordering, reverse=True)
    analysis = f"Phim tham chiếu: {movie_label(source)}. "
    if source_genres:
        analysis += "Thể loại: " + ", ".join(GENRES[g] for g in sorted(source_genres) if g in GENRES) + ". "
    if source_themes:
        analysis += "Chủ đề nhận diện từ mô tả/từ khóa: " + ", ".join(sorted(source_themes)) + ". "
    analysis += "Mô tả phim: " + source.overview[:240].rstrip() + ("…" if len(source.overview) > 240 else "")
    analysis += "\nMình so sánh mô tả, chủ đề, từ khóa và thể loại để chọn phim gần nội dung; danh sách sắp theo " + ("điểm đánh giá." if prefs.sort_by == "rating" else "ngày phát hành mới nhất.")
    if not movies:
        analysis += " Chưa có phim đủ gần nội dung và thỏa các điều kiện của bạn trong dữ liệu hiện có."
    if not get_settings().tmdb_access_token:
        analysis += " Hiện chỉ so sánh được các phim đã lưu trên máy."
    return movies, {
        "reply": analysis, "_reasons": reasons,
        "catalog_source": "cached" if remote_failed else "tmdb" if get_settings().tmdb_access_token else "local",
        "reference_movie": {"tmdb_id": source.tmdb_id, "title": source.title, "year": prefs.reference_year,
                            "overview": source.overview, "themes": sorted(source_themes)},
    }
