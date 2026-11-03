import os
from datetime import date

# Set before backend imports: collecting tests must never open the user's DB
# or inherit real cloud credentials from .env / the shell.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "moviemate-test-secret-not-for-production-0001"
os.environ["TMDB_ACCESS_TOKEN"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["OTEL_SDK_DISABLED"] = "true"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.db import Base, create_sqlite_engine, get_db
from backend.main import _attempts, app
from backend.models import Movie


@pytest.fixture(autouse=True)
def isolated_services(monkeypatch):
    import httpx
    import requests
    from backend import tmdb
    from backend.chat_service import conversations

    def blocked_http(*args, **kwargs):
        raise AssertionError(
            "Real HTTP is disabled in tests; mock the external service."
        )

    async def blocked_async_http(*args, **kwargs):
        blocked_http()

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked_http)
    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", blocked_async_http
    )
    monkeypatch.setattr(requests.sessions.Session, "request", blocked_http)
    monkeypatch.setattr(get_settings(), "gemini_api_key", "")
    monkeypatch.setattr(get_settings(), "tmdb_access_token", "")
    monkeypatch.setattr(get_settings(), "cookie_secure", False)
    monkeypatch.setattr(
        get_settings(), "allowed_origins", "http://127.0.0.1:8000,http://localhost:8000"
    )
    conversations.items.clear()
    tmdb._cache.clear()
    _attempts.clear()
    yield
    conversations.items.clear()
    tmdb._cache.clear()
    _attempts.clear()


@pytest.fixture(scope="session")
def test_engine(tmp_path_factory):
    path = tmp_path_factory.mktemp("database") / "test.db"
    test_engine = create_sqlite_engine("sqlite:///" + path.as_posix())
    Base.metadata.create_all(test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def db(test_engine):
    with test_engine.connect() as connection:
        transaction = connection.begin()
        session = Session(
            connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        session.add_all(
            [
                Movie(
                    tmdb_id=862,
                    title="Toy Story",
                    original_title="Toy Story",
                    overview="Một chuyến phiêu lưu đồ chơi.",
                    release_date=date(1995, 11, 22),
                    runtime=81,
                    genre_ids=[16, 35, 10751],
                    original_language="en",
                    tmdb_rating=8.0,
                    popularity=90,
                    cast_names=[],
                ),
                Movie(
                    tmdb_id=157336,
                    title="Interstellar",
                    original_title="Interstellar",
                    overview="Một chuyến đi qua vũ trụ.",
                    release_date=date(2014, 11, 7),
                    runtime=169,
                    genre_ids=[878, 18],
                    original_language="en",
                    tmdb_rating=8.4,
                    popularity=100,
                    cast_names=[],
                ),
                Movie(
                    tmdb_id=372058,
                    title="Your Name.",
                    original_title="Your Name.",
                    overview="Câu chuyện kết nối hai người trẻ.",
                    release_date=date(2016, 8, 26),
                    runtime=106,
                    genre_ids=[16, 10749, 18],
                    original_language="ja",
                    tmdb_rating=8.5,
                    popularity=80,
                    cast_names=[],
                ),
            ]
        )
        session.commit()
        yield session
        session.close()
        transaction.rollback()


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "tmdb_access_token", "")
    monkeypatch.setattr(get_settings(), "gemini_api_key", "")
    monkeypatch.setattr(get_settings(), "ai_provider", "gemini")
    _attempts.clear()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def account(client):
    response = client.post(
        "/api/auth/register",
        json={
            "name": "Người xem",
            "email": "viewer@example.com",
            "password": "a-good-password",
        },
    )
    assert response.status_code == 201
    return response.json()
