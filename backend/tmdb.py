from datetime import date, datetime, timezone
from threading import Lock
from time import monotonic

import httpx
from fastapi import HTTPException
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Movie

GENRES = {
    28: "Hành động",
    12: "Phiêu lưu",
    16: "Hoạt hình",
    35: "Hài",
    80: "Tội phạm",
    99: "Tài liệu",
    18: "Chính kịch",
    10751: "Gia đình",
    14: "Giả tưởng",
    36: "Lịch sử",
    27: "Kinh dị",
    10402: "Âm nhạc",
    9648: "Bí ẩn",
    10749: "Lãng mạn",
    878: "Khoa học viễn tưởng",
    10770: "Phim truyền hình",
    53: "Giật gân",
    10752: "Chiến tranh",
    37: "Cao bồi",
}
_cache: dict = {}
_lock = Lock()


def tmdb_get(path: str, **params):
    token = get_settings().tmdb_access_token
    if not token:
        raise HTTPException(503, "Chưa cấu hình TMDB_ACCESS_TOKEN trong .env.")
    params = {"language": "vi-VN", **params}
    key = (path, tuple(sorted(params.items())))
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > monotonic():
            return cached[1]
    try:
        response = httpx.get(
            "https://api.themoviedb.org/3/" + path.lstrip("/"),
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=12,
        )
        if response.status_code == 404:
            raise HTTPException(404, "Không tìm thấy phim trên TMDB.")
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(
            502, "Không thể kết nối TMDB. Vui lòng thử lại sau."
        ) from None
    with _lock:
        if len(_cache) >= 256:
            _cache.clear()
        _cache[key] = (monotonic() + 300, data)
    return data


def save_movies(db: Session, rows: list[dict], *, details=False):
    now = datetime.now(timezone.utc)
    for item in rows:
        if item.get("adult") or not item.get("id"):
            continue
        raw_date = item.get("release_date")
        try:
            release_date = date.fromisoformat(raw_date) if raw_date else None
        except ValueError:
            release_date = None
        values = dict(
            tmdb_id=item["id"],
            title=item.get("title") or item.get("original_title") or "Chưa có tên",
            original_title=item.get("original_title", ""),
            overview=item.get("overview", ""),
            poster_path=item.get("poster_path"),
            backdrop_path=item.get("backdrop_path"),
            release_date=release_date,
            genre_ids=item.get("genre_ids")
            or [g["id"] for g in item.get("genres", [])],
            original_language=item.get("original_language", ""),
            tmdb_rating=item.get("vote_average", 0),
            popularity=item.get("popularity", 0),
            updated_at=now,
        )
        if details:
            trailers = [
                v
                for v in item.get("videos", {}).get("results", [])
                if v.get("site") == "YouTube" and v.get("type") == "Trailer"
            ]
            values.update(
                runtime=item.get("runtime") or None,
                cast_names=[
                    a["name"] for a in item.get("credits", {}).get("cast", [])[:8]
                ],
                trailer_key=trailers[0]["key"] if trailers else None,
                details_fetched_at=now,
            )
        stmt = insert(Movie).values(**values)
        # List responses must not erase runtime, cast, or detail freshness.
        updates = {k: getattr(stmt.excluded, k) for k in values if k != "tmdb_id"}
        # Keep richer local detail translations when the list lacks an overview.
        if not values["overview"]:
            updates.pop("overview")
        db.execute(
            stmt.on_conflict_do_update(index_elements=[Movie.tmdb_id], set_=updates)
        )
    db.commit()
    db.expire_all()
