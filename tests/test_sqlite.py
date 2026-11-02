from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from backend.config import get_settings
from backend.models import Movie, Review, User, Watchlist


def test_sqlite_json_exact_genre_and_foreign_keys(client, db, account):
    db.add(Movie(tmdb_id=999, title="Exact genre test", genre_ids=[116], cast_names=[]))
    db.commit()
    assert [
        m["tmdb_id"] for m in client.get("/api/movies?genre=16").json()["items"]
    ] == [862, 372058]
    assert db.scalar(text("PRAGMA foreign_keys")) == 1
    with pytest.raises(IntegrityError):
        db.add(Watchlist(user_id=account["id"], movie_tmdb_id=999999, status="watched"))
        db.flush()
    db.rollback()
    client.put("/api/watchlist/862", json={"status": "watched"})
    client.put(
        "/api/movies/862/reviews/me",
        json={"rating": 8, "content": "Review để kiểm tra xóa liên quan."},
    )
    db.execute(delete(User).where(User.id == account["id"]))
    db.commit()
    assert db.scalar(select(func.count()).select_from(Watchlist)) == 0
    assert db.scalar(select(func.count()).select_from(Review)) == 0


def test_sqlite_detail_cache_uses_aware_utc(client, db, monkeypatch):
    movie = db.get(Movie, 862)
    movie.details_fetched_at = datetime.now(timezone.utc)
    db.commit()
    db.expire_all()
    assert db.get(Movie, 862).details_fetched_at.tzinfo == timezone.utc
    monkeypatch.setattr(get_settings(), "tmdb_access_token", "test-token")

    def unexpected(*args, **kwargs):
        pytest.fail("Fresh cached detail must not call TMDB again.")

    monkeypatch.setattr("backend.main.tmdb_get", unexpected)
    assert client.get("/api/movies/862").status_code == 200
