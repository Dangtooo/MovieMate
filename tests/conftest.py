from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.db import Base, create_sqlite_engine, get_db
from backend.main import _attempts, app
from backend.models import Movie


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
    monkeypatch.setattr(get_settings(), "ai_provider", "rules")
    _attempts.clear()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client
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
