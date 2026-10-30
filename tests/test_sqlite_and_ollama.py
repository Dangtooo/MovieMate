from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
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


def test_ollama_local_schema_history_and_no_cloud(client, monkeypatch):
    calls = []

    def local_post(url, **kwargs):
        calls.append((url, kwargs))
        assert url == "http://127.0.0.1:11434/api/chat"
        body = kwargs["json"]
        assert body["model"] == "qwen3:1.7b"
        assert body["stream"] is False and body["think"] is False
        assert body["format"]["type"] == "object"
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][1]["content"] == "Hoạt hình nhé"
        assert kwargs["trust_env"] is False
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "message": {
                    "content": '{"genre_ids":[16,999999],"max_runtime":120,"intro":"Mình tìm hoạt hình dưới hai giờ nhé."}'
                }
            },
        )

    monkeypatch.setattr("backend.ai.httpx.post", local_post)
    response = client.post(
        "/api/chat",
        json={
            "provider": "ollama",
            "message": "Dưới 2 tiếng",
            "history": [{"role": "user", "content": "Hoạt hình nhé"}],
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["mode"] == "ollama" and result["model"] == "qwen3:1.7b"
    assert result["preferences"]["genre_ids"] == [16]
    assert len(result["movies"]) == 2 and len(calls) == 1


@pytest.mark.parametrize("broken", ["offline", "invalid-json", "invalid-schema"])
def test_ollama_failures_are_explicit_without_cloud_fallback(
    client, monkeypatch, broken
):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "cloud-key-must-not-be-used")

    def local_post(url, **kwargs):
        assert url.startswith("http://127.0.0.1:11434/")
        if broken == "offline":
            raise httpx.ConnectError("offline")
        value = "not json" if broken == "invalid-json" else '{"max_runtime":-1}'
        return SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: {"message": {"content": value}}
        )

    monkeypatch.setattr("backend.ai.httpx.post", local_post)
    result = client.post(
        "/api/chat", json={"provider": "ollama", "message": "Phim hài dưới 2 tiếng"}
    ).json()
    assert result["mode"] == "rules_fallback" and result["model"] is None
    assert "Qwen local" in result["provider_notice"]
    assert [m["tmdb_id"] for m in result["movies"]] == [862]


def test_model_status_and_explicit_provider_validation(client, monkeypatch):
    monkeypatch.setattr(
        "backend.ai.httpx.get",
        lambda *a, **k: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"models": [{"name": "qwen3:1.7b"}]},
        ),
    )
    result = client.get("/api/ai/providers").json()
    local = next(p for p in result["providers"] if p["id"] == "ollama")
    assert local["ready"] and local["model"] == "qwen3:1.7b"
    assert "gemini_api_key" not in result
    assert (
        client.post(
            "/api/chat", json={"provider": "unknown", "message": "Gợi ý phim"}
        ).status_code
        == 422
    )


def test_auto_uses_configured_provider(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_provider", "ollama")
    monkeypatch.setattr(
        "backend.ai.httpx.post",
        lambda *a, **k: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"message": {"content": '{"genre_ids":[16]}'}},
        ),
    )
    assert (
        client.post("/api/chat", json={"message": "Hoạt hình"}).json()["mode"]
        == "ollama"
    )
