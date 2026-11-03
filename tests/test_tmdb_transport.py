"""Mock the HTTP boundary while exercising the real TMDB cache/error wrapper."""

import httpx
import pytest
from fastapi import HTTPException

from backend import tmdb
from backend.config import get_settings


def test_missing_token_fails_before_network():
    with pytest.raises(HTTPException) as error:
        tmdb.tmdb_get("movie/862")
    assert error.value.status_code == 503


def test_cache_hit_expiry_and_language_separation(monkeypatch):
    monkeypatch.setattr(get_settings(), "tmdb_access_token", "fake-token")
    clock = [1000.0]
    monkeypatch.setattr(tmdb, "monotonic", lambda: clock[0])
    calls = []

    def get(url, **kwargs):
        calls.append(kwargs)
        return httpx.Response(
            200, json={"request_number": len(calls)}, request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(tmdb.httpx, "get", get)
    assert tmdb.tmdb_get("movie/862") == tmdb.tmdb_get("movie/862")
    assert len(calls) == 1
    assert calls[0]["params"]["language"] == "vi-VN"
    assert calls[0]["headers"]["Authorization"] == "Bearer fake-token"
    tmdb.tmdb_get("movie/862", language="en")
    assert len(calls) == 2
    clock[0] += 301
    assert tmdb.tmdb_get("movie/862")["request_number"] == 3


@pytest.mark.parametrize(
    "failure,expected",
    [(404, 404), (429, 502), (500, 502), ("timeout", 502), ("invalid-json", 502)],
)
def test_transport_failures_are_sanitized_and_not_cached(
    monkeypatch, failure, expected
):
    monkeypatch.setattr(get_settings(), "tmdb_access_token", "private-test-token")
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        if failure == "timeout":
            raise httpx.ReadTimeout("private-provider-detail")
        return httpx.Response(
            200 if failure == "invalid-json" else failure,
            text="private-provider-detail",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(tmdb.httpx, "get", get)
    for _ in range(2):
        with pytest.raises(HTTPException) as error:
            tmdb.tmdb_get("movie/862")
        assert error.value.status_code == expected
        assert "private-" not in error.value.detail
    assert len(calls) == 2


def test_unavailable_optional_trailers_do_not_discard_movie_details(monkeypatch):
    def get(path, **params):
        if path == "movie/862":
            return {
                "id": 862,
                "title": "Toy Story",
                "original_language": "en",
                "videos": {"results": []},
            }
        raise HTTPException(502, "Unavailable videos")

    monkeypatch.setattr(tmdb, "tmdb_get", get)
    detail = tmdb.get_movie_details(862)
    assert detail["title"] == "Toy Story"
    assert detail["videos"]["results"] == []
