"""Reject unsafe/contradictory model arguments before external retrieval."""

import pytest

from backend.chat_tools import MovieTools


@pytest.mark.parametrize(
    "filters",
    [
        {"sort_by": "random"},
        {"min_rating": 11},
        {"min_rating": -1},
        {"min_runtime": -1},
        {"max_runtime": 601},
        {"year_from": 2024, "year_to": 2020},
        {"min_runtime": 150, "max_runtime": 90},
        {"language": "english"},
        {"language": "ja,ko"},
        {"watch_provider": "Netflix", "watch_country": "vn"},
    ],
)
def test_discovery_rejects_invalid_filters_without_request(db, monkeypatch, filters):
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid model arguments caused external retrieval.")

    monkeypatch.setattr("backend.chat_tools.tmdb_get", unexpected)
    result = MovieTools(db, {}, set()).discover_movies([], [], [], [], [], **filters)
    assert result.get("error") and result["movies"] == []


@pytest.mark.parametrize(
    "category,region", [("unknown", "VN"), ("trending", "Vietnam"), ("upcoming", "vn")]
)
def test_cinema_list_rejects_invalid_category_or_market(db, category, region):
    tools = MovieTools(db, {}, set())
    assert tools.movie_lists(category, region).get("error")
    assert tools.calls == 0
