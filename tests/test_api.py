from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
from fastapi import HTTPException
from sqlalchemy import func, select

from backend.config import get_settings
from backend.models import Movie, Review, User, Watchlist
from backend.tmdb import save_movies


def test_schema_uses_only_tmdb_id():
    assert list(Movie.__table__.primary_key.columns.keys()) == ["tmdb_id"]
    assert "id" not in Movie.__table__.columns
    assert (
        next(iter(Review.__table__.c.movie_tmdb_id.foreign_keys)).target_fullname
        == "movies.tmdb_id"
    )
    assert (
        next(iter(Watchlist.__table__.c.movie_tmdb_id.foreign_keys)).target_fullname
        == "movies.tmdb_id"
    )


def test_catalog_search_filter_and_health(client):
    assert client.get("/").status_code == 200
    assert client.get("/api/health").json()["database"] == "sqlite"
    assert (
        client.get("/api/movies?q=interstellar").json()["items"][0]["tmdb_id"] == 157336
    )
    assert len(client.get("/api/movies?genre=16").json()["items"]) == 2
    assert client.get("/api/movies?year=1995").json()["total"] == 1
    assert client.get("/api/movies?q=%25").json()["total"] == 0
    assert client.get("/api/movies?page=501").status_code == 422
    assert client.get("/api/movies?genre=9999").status_code == 422
    assert client.get("/api/movies/99999999").status_code == 404


def test_auth_hash_cookie_login_logout(client, db, account):
    user = db.get(User, account["id"])
    assert user.password_hash != "a-good-password"
    assert user.password_hash.startswith("$argon2")
    assert client.get("/api/auth/me").json()["id"] == user.id
    assert (
        "HttpOnly"
        in client.post(
            "/api/auth/login",
            json={"email": "viewer@example.com", "password": "a-good-password"},
        ).headers["set-cookie"]
    )
    assert (
        client.post(
            "/api/auth/register",
            json={
                "name": "Another",
                "email": "VIEWER@example.com",
                "password": "a-good-password",
            },
        ).status_code
        == 409
    )
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").json() is None
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "viewer@example.com", "password": "wrong-password"},
        ).status_code
        == 401
    )


def test_review_create_update_delete_and_average(client, db, account):
    path = "/api/movies/862/reviews/me"
    payload = {
        "rating": 8,
        "content": "Một bộ phim rất đáng xem.",
        "contains_spoiler": True,
    }
    assert client.put(path, json=payload).status_code == 200
    original_id = client.get(path).json()["id"]
    payload.update(rating=9, content="Cập nhật cảm nhận sau khi xem lại.")
    assert client.put(path, json=payload).json()["id"] == original_id
    assert db.scalar(select(func.count()).select_from(Review)) == 1
    movie = client.get("/api/movies/862").json()
    assert movie["community_rating"] == 9.0 and movie["review_count"] == 1
    assert movie["tmdb_rating"] == 8.0
    assert client.get("/api/movies/862/reviews").json()["items"][0]["contains_spoiler"]
    assert client.delete(path).status_code == 204
    assert client.get("/api/movies/862").json()["community_rating"] is None


def test_review_ownership_and_auth(client, db, account):
    path = "/api/movies/862/reviews/me"
    client.put(path, json={"rating": 8, "content": "Review thuộc tài khoản thứ nhất."})
    client.post("/api/auth/logout")
    assert (
        client.put(
            path, json={"rating": 9, "content": "Gửi khi chưa đăng nhập."}
        ).status_code
        == 401
    )
    assert client.delete(path).status_code == 401
    client.post(
        "/api/auth/register",
        json={
            "name": "Tài khoản hai",
            "email": "second@example.com",
            "password": "a-good-password",
        },
    )
    assert client.get(path).json() is None
    client.delete(path)
    assert db.scalar(select(func.count()).select_from(Review)) == 1


def test_review_and_account_validation(client, account):
    path = "/api/movies/862/reviews/me"
    assert (
        client.put(
            path, json={"rating": 11, "content": "Review đủ số ký tự."}
        ).status_code
        == 422
    )
    assert (
        client.put(
            path, json={"rating": 8.5, "content": "Review đủ số ký tự."}
        ).status_code
        == 422
    )
    assert client.put(path, json={"rating": 8, "content": " " * 15}).status_code == 422
    assert (
        client.post(
            "/api/auth/register",
            json={
                "name": "  ",
                "email": "x@example.com",
                "password": "a-good-password",
            },
        ).status_code
        == 422
    )


def test_watchlist_upsert_and_watched_exclusion(client, db, account):
    path = "/api/watchlist/862"
    client.put(path, json={"status": "want_to_watch"})
    client.put(path, json={"status": "watched"})
    assert db.scalar(select(func.count()).select_from(Watchlist)) == 1
    assert client.get("/api/watchlist?status=watched").json()["total"] == 1
    assert client.get("/api/watchlist?status=want_to_watch").json()["total"] == 0
    result = client.post(
        "/api/chat", json={"message": "Phim hoạt hình dưới 2 tiếng"}
    ).json()
    assert result["mode"] == "rules"
    assert 862 not in [m["tmdb_id"] for m in result["movies"]]
    assert [m["tmdb_id"] for m in result["movies"]] == [372058]
    client.delete(path)
    assert client.get("/api/watchlist").json()["total"] == 0


def test_chat_constraints_and_no_fabrication(client):
    result = client.post(
        "/api/chat", json={"message": "Phim hài dưới 2 tiếng, tránh kinh dị"}
    ).json()
    assert result["preferences"]["max_runtime"] == 120
    assert 27 in result["preferences"]["excluded_genre_ids"]
    assert [m["tmdb_id"] for m in result["movies"]] == [862]
    assert all(m["runtime"] <= 120 for m in result["movies"])
    empty = client.post("/api/chat", json={"message": "Phim Hàn dưới 2 tiếng"}).json()
    assert empty["movies"] == []
    assert client.post("/api/chat", json={"message": " " * 10}).status_code == 422


def test_chat_history_constraints(client):
    result = client.post(
        "/api/chat",
        json={
            "message": "Dưới 2 tiếng nhé",
            "history": [
                {"role": "user", "content": "Hoạt hình Nhật Bản"},
                {"role": "assistant", "content": "Bạn muốn thời lượng bao lâu?"},
            ],
        },
    ).json()
    assert result["preferences"]["language"] == "ja"
    assert [m["tmdb_id"] for m in result["movies"]] == [372058]


def test_tmdb_list_upsert_preserves_detail(db):
    movie = db.get(Movie, 862)
    movie.details_fetched_at = datetime.now(timezone.utc)
    movie.cast_names = ["Tom Hanks"]
    db.commit()
    save_movies(
        db,
        [
            {
                "id": 862,
                "title": "Toy Story updated",
                "genre_ids": [16, 35],
                "vote_average": 8.1,
                "overview": "",
            }
        ],
    )
    movie = db.get(Movie, 862)
    assert movie.runtime == 81
    assert movie.cast_names == ["Tom Hanks"]
    assert movie.details_fetched_at is not None
    assert movie.overview == "Một chuyến phiêu lưu đồ chơi."


def test_external_listing_and_cache_fallback(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "tmdb_access_token", "test-token")
    calls = []

    def remote(path, **params):
        calls.append(path)
        return {
            "results": [
                {
                    "id": 999,
                    "title": "External movie",
                    "genre_ids": [18],
                    "release_date": "2020-01-01",
                    "vote_average": 7.0,
                }
            ],
            "total_results": 1,
            "total_pages": 1,
        }

    monkeypatch.setattr("backend.main.tmdb_get", remote)
    result = client.get("/api/movies").json()
    assert result["source"] == "tmdb"
    assert result["items"][0]["tmdb_id"] == 999
    assert calls == ["discover/movie"]

    def unavailable(*args, **kwargs):
        raise HTTPException(502, "Unavailable")

    monkeypatch.setattr("backend.main.tmdb_get", unavailable)
    fallback = client.get("/api/movies").json()
    assert fallback["source"] == "cached" and fallback["warning"]
    assert fallback["total"] == 4


def test_gemini_intent_and_failure_fallback(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "test-key")

    def remote(*args, **kwargs):
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": '{"genre_ids":[16],"max_runtime":120,"intro":"Tìm hoạt hình dưới hai giờ nhé."}'
                                }
                            ]
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr("backend.ai.httpx.post", remote)
    result = client.post(
        "/api/chat", json={"message": "Hoạt hình dưới 2 tiếng", "provider": "gemini"}
    ).json()
    assert result["mode"] == "gemini" and len(result["movies"]) == 2

    def failed(*args, **kwargs):
        raise httpx.ConnectError("Provider unavailable")

    monkeypatch.setattr("backend.ai.httpx.post", failed)
    assert (
        client.post(
            "/api/chat", json={"message": "Hoạt hình", "provider": "gemini"}
        ).json()["mode"]
        == "rules_fallback"
    )


def test_cross_origin_cookie_protection(client, account):
    assert (
        client.post(
            "/api/auth/logout", headers={"origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert client.get("/api/auth/me").json() is not None
    assert (
        client.post(
            "/api/auth/logout", headers={"origin": "http://127.0.0.1:8000"}
        ).status_code
        == 204
    )
    assert client.get("/").headers["x-content-type-options"] == "nosniff"
    assert "'unsafe-inline'" not in client.get("/").headers["content-security-policy"]
    assert (
        "https://cdn.jsdelivr.net"
        in client.get("/docs").headers["content-security-policy"]
    )


def test_chat_rate_limit(client):
    for _ in range(10):
        assert (
            client.post("/api/chat", json={"message": "Gợi ý phim"}).status_code == 200
        )
    assert client.post("/api/chat", json={"message": "Gợi ý phim"}).status_code == 429
