"""Exercise tools, session isolation and the actual ADK runner without paid APIs."""

import pytest
from fastapi import HTTPException

from backend import chat_service
from backend.chat_agent import AgentAnswer
from backend.chat_service import Conversation, ConversationStore
from backend.chat_tools import MovieTools, movie_card, rank_movies
from backend.config import get_settings


def row(mid, title="A film", **extra):
    return {
        "id": mid,
        "title": title,
        "release_date": "2020-01-01",
        "vote_average": 8.0,
        "vote_count": 200,
        "popularity": 10,
        "genre_ids": [18],
        **extra,
    }


def test_ranking_vote_weighting_deduplication_and_unknown_runtime():
    rows = [
        row(1, vote_average=10, vote_count=1),
        row(2, vote_average=8, vote_count=2000),
        row(2, vote_average=8, vote_count=2000),
        row(3, runtime=80),
        row(4, runtime=150),
    ]
    assert rank_movies(rows)[0]["id"] == 2
    assert len(rank_movies(rows, limit=20)) == 4
    assert rank_movies(rows, "shortest")[0]["id"] == 3
    assert (
        rank_movies([row(1), row(2, release_date="2025-01-01")], "newest")[0]["id"] == 2
    )


def test_discover_external_filters_and_watched_exclusion(db, monkeypatch):
    calls = []

    def remote(path, **params):
        calls.append((path, params))
        if path == "genre/movie/list":
            return {
                "genres": [{"id": 35, "name": "Comedy"}, {"id": 27, "name": "Horror"}]
            }
        return {
            "results": [row(10), row(11), row(12, release_date="2099-01-01")],
            "total_pages": 1,
        }

    monkeypatch.setattr("backend.chat_tools.tmdb_get", remote)
    tools = MovieTools(db, {}, {10})
    result = tools.discover_movies(
        ["Comedy"],
        ["Horror"],
        [],
        [],
        [],
        language="ja",
        year_from=2020,
        min_rating=7,
        max_runtime=120,
        sort_by="newest",
    )
    assert [m["id"] for m in result["movies"]] == [11]
    params = next(p for path, p in calls if path == "discover/movie")
    assert params["with_genres"] == "35" and params["without_genres"] == "27"
    assert (
        params["with_runtime.lte"] == 120 and params["with_original_language"] == "ja"
    )
    assert params["sort_by"] == "primary_release_date.desc"
    assert "vote_count.gte" not in params
    assert 11 in tools.evidence and 10 not in tools.evidence


def test_director_job_is_verified(db, monkeypatch):
    def remote(path, **params):
        if path == "search/person":
            return {
                "results": [
                    {
                        "id": 77,
                        "name": "A Director",
                        "known_for_department": "Directing",
                    }
                ]
            }
        if path == "discover/movie":
            assert params["with_crew"] == "77"
            return {"results": [row(10), row(11)], "total_pages": 1}
        return {
            "crew": [{"id": 77, "job": "Director" if "10/" in path else "Producer"}]
        }

    monkeypatch.setattr("backend.chat_tools.tmdb_get", remote)
    result = MovieTools(db, {}, set()).discover_movies([], [], [], [], ["A Director"])
    assert [m["id"] for m in result["movies"]] == [10]


def test_tools_require_verified_ids_and_handle_external_error(db, monkeypatch):
    def failed(*args, **kwargs):
        raise HTTPException(502, "TMDB unavailable")

    monkeypatch.setattr("backend.chat_tools.tmdb_get", failed)
    tools = MovieTools(db, {}, set())
    assert "error" in tools.movie_details(999)
    assert "error" in tools.related_movies(999)
    assert "error" in tools.watch_providers(999)
    assert "error" in tools.rank_candidates([999])
    assert tools.search_movies("Missing")["error"] == "TMDB unavailable"
    assert tools.calls == 1


def test_provider_country_and_trailer_are_grounded(db, monkeypatch):
    data = {"results": {"US": {"flatrate": [{"provider_name": "Netflix"}]}}}
    monkeypatch.setattr("backend.chat_tools.tmdb_get", lambda *a, **k: data)
    tools = MovieTools(db, {10: row(10)}, set())
    assert tools.watch_providers(10, "VN")["stream"] == []
    assert tools.watch_providers(10, "US")["stream"] == ["Netflix"]
    assert movie_card(row(10, poster_path='/bad".jpg'))["poster_url"] is None
    assert movie_card(row(10))["trailer_url"] is None


def test_details_and_followup_ranking(db, monkeypatch):
    def remote(path, **params):
        return row(
            10,
            runtime=90,
            credits={
                "cast": [{"name": "Actor"}],
                "crew": [{"name": "Director", "job": "Director"}],
            },
            videos={
                "results": [
                    {
                        "site": "YouTube",
                        "type": "Trailer",
                        "official": True,
                        "key": "abcdefghijk",
                    }
                ]
            },
        )

    monkeypatch.setattr("backend.chat_tools.tmdb_get", remote)
    tools = MovieTools(db, {10: row(10), 11: row(11)}, set())
    details = tools.movie_details(10)
    assert details["directors"] == ["Director"]
    assert details["trailer_url"] == "https://www.youtube.com/watch?v=abcdefghijk"
    result = tools.rank_candidates([10, 11], "shortest")
    assert result["movies"][0]["runtime"] == 90
    assert result["missing_runtime_ids"] == [11]


def test_request_budget(db, monkeypatch):
    monkeypatch.setattr("backend.chat_tools.tmdb_get", lambda *a, **k: {"results": []})
    tools = MovieTools(db, {}, set())
    tools.calls = 30
    assert "giới hạn" in tools.search_movies("A")["error"]


def test_owner_isolation_and_parallel_turn_rejection():
    store = ConversationStore()
    with store.acquire("first", "same-id") as state:
        state.last_ids = [10]
        with pytest.raises(HTTPException) as busy:
            with store.acquire("first", "same-id"):
                pass
        assert busy.value.status_code == 409
        with store.acquire("second", "same-id") as other:
            assert other.last_ids == []
    with store.acquire("first", "same-id") as state:
        assert state.last_ids == [10]


def test_missing_key_explicit_and_provider_status(client):
    result = client.post(
        "/api/chat", json={"message": "Xin chào", "session_id": "no-key"}
    )
    assert result.status_code == 503
    assert "GEMINI_API_KEY" in result.json()["detail"]
    data = client.get("/api/ai/providers").json()
    assert data["providers"][0]["id"] == "gemini"
    assert not data["providers"][0]["ready"]
    assert "gemini_api_key" not in str(data)


def test_service_multi_turn_and_browser_isolation(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "test-key")
    histories = []

    async def fake(state, message, tools):
        histories.append(list(state.turns))
        tools.evidence[10] = row(10, "Verified film")
        return AgentAnswer(reply="Đây là phim vừa tra cứu.", movie_ids=[10])

    monkeypatch.setattr(chat_service, "run_agent", fake)
    payload = {"message": "Tìm phim", "session_id": "memory"}
    assert (
        client.post("/api/chat", json=payload).json()["movies"][0]["title"]
        == "Verified film"
    )
    assert (
        client.post(
            "/api/chat", json={**payload, "message": "Phim đó dài bao lâu?"}
        ).status_code
        == 200
    )
    assert len(histories[1]) == 2
    client.cookies.clear()
    assert client.post("/api/chat", json=payload).status_code == 200
    assert histories[2] == []


def test_service_no_silent_fallback_on_agent_failure(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "test-key")

    async def broken(*args):
        raise ValueError("invalid response")

    monkeypatch.setattr(chat_service, "run_agent", broken)
    result = client.post(
        "/api/chat", json={"message": "Phim hài", "session_id": "failure"}
    )
    assert result.status_code == 502
    assert "invalid response" not in result.text


def test_adk_actual_runner_calls_function_and_uses_history(db, monkeypatch):
    """Use ADK BaseLlm to drive a real Runner through search -> tool -> answer."""
    import asyncio
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types
    from backend import chat_agent

    requests = []

    class FakeModel(BaseLlm):
        model: str = "fake"

        async def generate_content_async(self, llm_request, stream=False):
            requests.append(llm_request)
            has_result = any(
                p.function_response for c in llm_request.contents for p in c.parts or []
            )
            if has_result:
                yield LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                text='{"reply":"Phim tìm được là Verified film.","movie_ids":[10]}'
                            )
                        ],
                    )
                )
            else:
                yield LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                function_call=types.FunctionCall(
                                    name="search_movies",
                                    args={"title": "Verified film"},
                                )
                            )
                        ],
                    )
                )

    monkeypatch.setattr(chat_agent, "ConfiguredGemini", lambda **kwargs: FakeModel())
    monkeypatch.setattr(
        "backend.chat_tools.tmdb_get",
        lambda *a, **k: {"results": [row(10, "Verified film")]},
    )
    state = Conversation()
    state.turns.append(
        {"role": "user", "content": "Tôi thích phim khoa học viễn tưởng"}
    )
    tools = MovieTools(db, {}, set())
    answer = asyncio.run(chat_agent.run_agent(state, "Tìm phim giúp tôi", tools))
    assert answer.movie_ids == [10] and tools.evidence[10]["title"] == "Verified film"
    assert len(requests) == 2
    assert any(
        "khoa học viễn tưởng" in (p.text or "")
        for c in requests[0].contents
        for p in c.parts or []
    )


def test_adk_rejects_unverified_output(db, monkeypatch):
    import asyncio
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types
    from backend import chat_agent

    class FakeModel(BaseLlm):
        model: str = "fake"

        async def generate_content_async(self, llm_request, stream=False):
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(text='{"reply":"Invented","movie_ids":[999]}')],
                )
            )

    monkeypatch.setattr(chat_agent, "ConfiguredGemini", lambda **kwargs: FakeModel())
    with pytest.raises(ValueError, match="chưa được tra cứu"):
        asyncio.run(
            chat_agent.run_agent(Conversation(), "Tìm phim", MovieTools(db, {}, set()))
        )


def test_shortest_discovery_fetches_missing_runtime(db, monkeypatch):
    def remote(path, **params):
        if path == "discover/movie":
            return {"results": [row(10), row(11)], "total_pages": 1}
        mid = int(path.split("/")[1])
        return row(mid, runtime=150 if mid == 10 else 80)

    monkeypatch.setattr("backend.chat_tools.tmdb_get", remote)
    result = MovieTools(db, {}, set()).discover_movies(
        [], [], [], [], [], sort_by="shortest"
    )
    assert [m["id"] for m in result["movies"]] == [11, 10]
    assert result["movies"][0]["runtime"] == 80


def test_upcoming_list_uses_external_endpoint_and_release_date(db, monkeypatch):
    def remote(path, **params):
        assert path == "movie/upcoming" and params["region"] == "VN"
        return {"results": [row(10), row(11, release_date="2099-01-01")]}

    monkeypatch.setattr("backend.chat_tools.tmdb_get", remote)
    result = MovieTools(db, {}, set()).movie_lists("upcoming")
    assert [m["id"] for m in result["movies"]] == [11]


@pytest.mark.parametrize(
    "code, expected_status, expected_text",
    [
        (429, 429, "quota"),
        (403, 503, "quyền"),
        (404, 503, "GEMINI_MODEL"),
        (500, 502, "Dịch vụ Gemini"),
    ],
)
def test_upstream_errors_are_distinguished(
    client, monkeypatch, code, expected_status, expected_text
):
    from google.genai.errors import ClientError

    monkeypatch.setattr(get_settings(), "gemini_api_key", "test-key")

    async def failed(*args):
        raise ClientError(
            code, {"error": {"code": code, "message": "private-provider-error"}}
        )

    monkeypatch.setattr(chat_service, "run_agent", failed)
    r = client.post(
        "/api/chat", json={"session_id": "error-type", "message": "Tìm phim"}
    )
    assert r.status_code == expected_status
    assert expected_text in r.json()["detail"]
    assert "private-provider-error" not in r.text


def test_adk_output_length_is_not_reported_as_quota(db, monkeypatch):
    import asyncio
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types
    from backend import chat_agent

    class FakeModel(BaseLlm):
        model: str = "fake"

        async def generate_content_async(self, llm_request, stream=False):
            yield LlmResponse(
                content=types.Content(
                    role="model", parts=[types.Part(text='{"reply":')]
                ),
                finish_reason=types.FinishReason.MAX_TOKENS,
            )

    monkeypatch.setattr(chat_agent, "ConfiguredGemini", lambda **kwargs: FakeModel())
    with pytest.raises(chat_agent.OutputTokenLimitError):
        asyncio.run(
            chat_agent.run_agent(Conversation(), "Tìm phim", MovieTools(db, {}, set()))
        )


def test_adk_finishes_with_structured_tool_and_corrects_unknown_id(db, monkeypatch):
    import asyncio
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types
    from backend import chat_agent

    calls = []

    class FakeModel(BaseLlm):
        model: str = "fake"

        async def generate_content_async(self, llm_request, stream=False):
            responses = [
                p.function_response
                for c in llm_request.contents
                for p in c.parts or []
                if p.function_response
            ]
            previous = [r for r in responses if r.name == "finish_answer"]
            ids = [10] if previous else [999]
            calls.append(ids)
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                name="finish_answer",
                                args={
                                    "reply": "Phim tương tự đã xác minh.",
                                    "movie_ids": ids,
                                },
                            )
                        )
                    ],
                )
            )

    monkeypatch.setattr(chat_agent, "ConfiguredGemini", lambda **kwargs: FakeModel())
    tools = MovieTools(db, {10: row(10)}, set())
    answer = asyncio.run(
        chat_agent.run_agent(Conversation(), "Phim giống Incantation?", tools)
    )
    assert calls == [[999], [10]]
    assert answer.movie_ids == [10]
    assert answer.reply == "Phim tương tự đã xác minh."


def test_named_similar_tool_resolves_title_and_excludes_reference(db, monkeypatch):
    calls = []

    def remote(path, **params):
        calls.append(path)
        if path == "search/movie":
            return {"results": [row(10, "Incantation")]}
        return {"results": [row(10, "Incantation"), row(11, "Similar horror")]}

    monkeypatch.setattr("backend.chat_tools.tmdb_get", remote)
    tools = MovieTools(db, {}, set())
    result = tools.find_similar_movies("Incantation")
    assert [m["id"] for m in result["movies"]] == [11]
    assert result["reference"]["id"] == 10
    assert len(calls) == 3


def test_named_similar_tool_asks_about_remakes(db, monkeypatch):
    monkeypatch.setattr(
        "backend.chat_tools.tmdb_get",
        lambda *a, **k: {"results": [row(10, "It"), row(11, "It")]},
    )
    tools = MovieTools(db, {}, set())
    assert tools.find_similar_movies("It")["needs_clarification"]
    assert tools.calls == 1


def test_person_filmography_filters_exact_jobs_and_handles_ambiguity(db, monkeypatch):
    def remote(path, **params):
        if path == "search/person":
            return {"results": [{"id": 77, "name": "Christopher Nolan"}]}
        return {
            "name": "Christopher Nolan",
            "birthday": "1970-07-30",
            "movie_credits": {
                "crew": [
                    row(10, job="Director"),
                    row(11, job="Producer"),
                    row(12, job="Director", release_date="2099-01-01"),
                ]
            },
        }

    monkeypatch.setattr("backend.chat_tools.tmdb_get", remote)
    tools = MovieTools(db, {}, set())
    result = tools.person_information("Christopher Nolan", "director")
    assert [m["id"] for m in result["movies"]] == [10]
    assert result["person"]["birthday"] == "1970-07-30"
    assert result["total_credits"] == 2
    upcoming = tools.person_information("Christopher Nolan", "director", upcoming=True)
    assert [m["id"] for m in upcoming["movies"]] == [12]
    monkeypatch.setattr(
        "backend.chat_tools.tmdb_get",
        lambda *a, **k: {
            "results": [{"id": 1, "name": "Same"}, {"id": 2, "name": "Same"}]
        },
    )
    assert tools.person_information("Same")["needs_clarification"]


def test_collection_release_order_not_rating_or_plot_chronology(db, monkeypatch):
    def remote(path, **params):
        if path == "movie/10":
            return {"belongs_to_collection": {"id": 77}}
        assert path == "collection/77"
        return {
            "name": "A franchise",
            "parts": [
                row(12, release_date="2099-01-01"),
                row(11, release_date="2021-01-01"),
                row(10),
            ],
        }

    monkeypatch.setattr("backend.chat_tools.tmdb_get", remote)
    tools = MovieTools(db, {10: row(10)}, set())
    result = tools.movie_collection(10)
    assert [m["id"] for m in result["movies"]] == [10, 11, 12]
    assert result["part_count"] == 3
    assert not result["release_order"][-1]["released"]
    assert "error" in tools.movie_collection(999)


def test_streaming_discovery_uses_country_and_subscription_filter(db, monkeypatch):
    def remote(path, **params):
        if path == "watch/providers/movie":
            assert params["watch_region"] == "VN"
            return {"results": [{"provider_name": "Netflix", "provider_id": 8}]}
        assert params["with_watch_providers"] == "8"
        assert params["watch_region"] == "VN"
        assert params["with_watch_monetization_types"] == "flatrate"
        return {"results": [row(10)], "total_pages": 1}

    monkeypatch.setattr("backend.chat_tools.tmdb_get", remote)
    result = MovieTools(db, {}, set()).discover_movies(
        [], [], [], [], [], watch_provider="Netflix"
    )
    assert result["movies"][0]["id"] == 10


def test_comparison_fetches_details_and_keeps_missing_data_explicit(db, monkeypatch):
    tools = MovieTools(db, {10: row(10), 11: row(11)}, set())
    monkeypatch.setattr(
        tools,
        "movie_details",
        lambda mid: (
            {"id": 10, "title": "Verified", "runtime": 90}
            if mid == 10
            else {"error": "Unavailable"}
        ),
    )
    result = tools.compare_movies([10, 11])
    assert result["movies"][0]["runtime"] == 90
    assert result["errors"] == [{"id": 11, "error": "Unavailable"}]
    assert "error" in tools.compare_movies([10, 999])


def test_terminal_logs_tool_names_arguments_results_and_errors(db, monkeypatch, caplog):
    import asyncio
    import logging
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types
    from backend import chat_agent

    caplog.set_level(logging.INFO, logger="uvicorn.error")

    class FakeModel(BaseLlm):
        model: str = "fake"

        async def generate_content_async(self, llm_request, stream=False):
            responses = [
                p.function_response
                for c in llm_request.contents
                for p in c.parts or []
                if p.function_response
            ]
            has_error = any(r.name == "finish_answer" for r in responses)
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                name="finish_answer",
                                args={
                                    "reply": "private-generated-reply",
                                    "movie_ids": [10] if has_error else [999],
                                },
                            )
                        )
                    ],
                )
            )

    monkeypatch.setattr(chat_agent, "ConfiguredGemini", lambda **k: FakeModel())
    asyncio.run(
        chat_agent.run_agent(
            Conversation(), "Tìm phim", MovieTools(db, {10: row(10)}, set())
        )
    )
    assert "TOOL START finish_answer" in caplog.text
    assert '"movie_ids": [999]' in caplog.text
    assert "TOOL ERROR finish_answer" in caplog.text
    assert "TOOL DONE finish_answer" in caplog.text
    assert "duration=" in caplog.text
    assert "private-generated-reply" not in caplog.text


def test_plain_text_answer_after_successful_tool_is_accepted(db, monkeypatch, caplog):
    import asyncio
    import logging
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types
    from backend import chat_agent

    caplog.set_level(logging.INFO, logger="uvicorn.error")

    class FakeModel(BaseLlm):
        model: str = "fake"

        async def generate_content_async(self, llm_request, stream=False):
            has_result = any(
                p.function_response for c in llm_request.contents for p in c.parts or []
            )
            if has_result:
                part = types.Part(
                    text="Bạn có thể xem Terrifier (2020), một phim kinh dị."
                )
            else:
                part = types.Part(
                    function_call=types.FunctionCall(
                        name="search_movies", args={"title": "Terrifier"}
                    )
                )
            yield LlmResponse(content=types.Content(role="model", parts=[part]))

    monkeypatch.setattr(chat_agent, "ConfiguredGemini", lambda **k: FakeModel())
    monkeypatch.setattr(
        "backend.chat_tools.tmdb_get",
        lambda *a, **k: {
            "results": [row(10, "Terrifier"), row(11, "Unmentioned film")]
        },
    )
    answer = asyncio.run(
        chat_agent.run_agent(
            Conversation(), "Gợi ý phim kinh dị", MovieTools(db, {}, set())
        )
    )
    assert answer.movie_ids == [10]
    assert "ANSWER DONE mode=text" in caplog.text
    assert "CHAT FAILED" not in caplog.text


def test_final_response_parser_keeps_unknown_json_ids_rejected():
    from backend.chat_agent import parse_final_answer

    with pytest.raises(ValueError, match="chưa được tra cứu"):
        parse_final_answer('{"reply":"Bad", "movie_ids":[999]}', {10: row(10)})
    assert parse_final_answer("Chào bạn!", {}).movie_ids == []
    with pytest.raises(ValueError, match="không có câu trả lời"):
        parse_final_answer("", {})


def test_prose_cards_match_full_titles_without_confusing_sequels():
    from backend.chat_agent import parse_final_answer

    evidence = {
        10: row(10, "Terrifier"),
        11: row(11, "Terrifier 2"),
        12: row(12, "Alien"),
    }
    assert parse_final_answer("Hãy xem Terrifier 2.", evidence).movie_ids == [11]
    assert parse_final_answer("Aliens là tên được nhắc đến.", evidence).movie_ids == []
