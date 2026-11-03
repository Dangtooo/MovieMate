"""Real ADK Runner executions with a scripted BaseLlm, never a cloud model."""

import asyncio
from types import SimpleNamespace

import pytest
from google.adk.agents.invocation_context import LlmCallsLimitExceededError
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from backend import chat_agent
from backend.chat_service import Conversation
from backend.chat_tools import MovieTools
from backend.config import get_settings
from backend.models import Movie


def finish(reply="Verified response", ids=None):
    return types.Part(
        function_call=types.FunctionCall(
            name="finish_answer", args={"reply": reply, "movie_ids": ids or []}
        )
    )


@pytest.fixture
def scripted_model(monkeypatch):
    def install(steps, client=None):
        sequence = iter(steps)
        requests = []

        class ScriptedModel(BaseLlm):
            model: str = "offline-scripted-model"

            async def generate_content_async(self, llm_request, stream=False):
                requests.append([c.model_copy(deep=True) for c in llm_request.contents])
                step = next(sequence)
                if isinstance(step, Exception):
                    raise step
                yield LlmResponse(content=types.Content(role="model", parts=step))

        model = ScriptedModel()
        if client is not None:
            model.__dict__["api_client"] = client
        monkeypatch.setattr(chat_agent, "ConfiguredGemini", lambda **kwargs: model)
        return requests

    return install


def test_runner_enforces_model_call_budget(db, monkeypatch, scripted_model):
    call = types.Part(
        function_call=types.FunctionCall(
            name="search_movies", args={"title": "Example"}
        )
    )
    seen = scripted_model([[call] for _ in range(10)])
    monkeypatch.setattr("backend.chat_tools.tmdb_get", lambda *a, **k: {"results": []})
    with pytest.raises(LlmCallsLimitExceededError):
        asyncio.run(
            chat_agent.run_agent(
                Conversation(), "Find films", MovieTools(db, {}, set())
            )
        )
    assert len(seen) == 8


def test_runner_sends_only_recent_bounded_history(db, scripted_model):
    state = Conversation()
    for i in range(16):
        state.turns.append(
            {
                "role": "user" if i % 2 == 0 else "assistant",
                "content": f"history-{i:02} " + "x" * 2000,
            }
        )
    seen = scripted_model([[finish()]])
    asyncio.run(
        chat_agent.run_agent(state, "Current question", MovieTools(db, {}, set()))
    )
    texts = [p.text for content in seen[0] for p in content.parts or [] if p.text]
    assert not any("history-07 " in t for t in texts)
    assert any(t.startswith("history-08 ") for t in texts)
    assert any(t.startswith("history-15 ") for t in texts)
    assert all(len(t) <= 1200 for t in texts if t.startswith("history-"))
    assert texts[-1] == "Current question"


@pytest.mark.parametrize(
    "invalid",
    [
        finish(reply=""),
        finish(reply="x" * 12001),
        finish(ids=list(range(1, 10))),
    ],
)
def test_finish_tool_returns_validation_error_and_allows_correction(
    db, scripted_model, invalid
):
    seen = scripted_model([[invalid], [finish("Corrected answer", [1])]])
    evidence = {i: {"id": i, "title": f"Film {i}"} for i in range(1, 10)}
    answer = asyncio.run(
        chat_agent.run_agent(
            Conversation(), "Find films", MovieTools(db, evidence, set())
        )
    )
    errors = [
        p.function_response.response
        for c in seen[1]
        for p in c.parts or []
        if p.function_response
    ]
    assert any("error" in response for response in errors)
    assert answer.movie_ids == [1] and answer.reply == "Corrected answer"


def test_thought_content_does_not_become_final_answer_or_movie_card(db, scripted_model):
    scripted_model(
        [
            [
                types.Part(text="Private reasoning mentions Toy Story", thought=True),
                types.Part(text="Hello, how can I help?"),
            ]
        ]
    )
    answer = asyncio.run(
        chat_agent.run_agent(
            Conversation(),
            "Hello",
            MovieTools(db, {862: {"id": 862, "title": "Toy Story"}}, set()),
        )
    )
    assert answer.reply == "Hello, how can I help?"
    assert answer.movie_ids == []


@pytest.mark.parametrize("mode", ["success", "model-failure", "cleanup-failure"])
def test_request_scoped_client_closes_both_interfaces(db, scripted_model, mode):
    closed = []

    async def close_async():
        closed.append("async")
        if mode == "cleanup-failure":
            raise RuntimeError("Cannot close async interface")

    def close_sync():
        closed.append("sync")

    client = SimpleNamespace(aio=SimpleNamespace(aclose=close_async), close=close_sync)
    step = RuntimeError("Model failed") if mode == "model-failure" else [finish()]
    scripted_model([step], client)
    if mode == "model-failure":
        with pytest.raises(RuntimeError, match="Model failed"):
            asyncio.run(
                chat_agent.run_agent(Conversation(), "Hello", MovieTools(db, {}, set()))
            )
    else:
        result = asyncio.run(
            chat_agent.run_agent(Conversation(), "Hello", MovieTools(db, {}, set()))
        )
        assert result.reply == "Verified response"
    assert closed == ["async", "sync"]


def test_gemini_client_uses_configured_key_instead_of_ambient_vertex_auth(monkeypatch):
    calls = []
    sentinel = object()

    def build_client(**kwargs):
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(get_settings(), "gemini_api_key", "fake-unit-test-key")
    monkeypatch.setattr(chat_agent, "Client", build_client)
    model = chat_agent.ConfiguredGemini(model="gemini-test")
    assert model.api_client is sentinel
    assert model.api_client is sentinel
    assert len(calls) == 1
    assert calls[0]["api_key"] == "fake-unit-test-key"
    assert calls[0]["vertexai"] is False


def test_http_to_runner_to_tool_and_followup_persists_verified_metadata(
    client, db, monkeypatch, scripted_model
):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "fake-unit-test-key")
    seen = scripted_model(
        [
            [
                types.Part(
                    function_call=types.FunctionCall(
                        name="search_movies", args={"title": "Verified Journey"}
                    )
                )
            ],
            [finish("A verified journey.", [10])],
            [
                types.Part(
                    function_call=types.FunctionCall(
                        name="movie_details", args={"movie_id": 10}
                    )
                )
            ],
            [finish("The verified runtime is 90 minutes.", [10])],
        ]
    )
    movie = {
        "id": 10,
        "title": "Verified Journey",
        "release_date": "2020-01-01",
        "genre_ids": [18],
        "vote_average": 8.0,
        "poster_path": "/verified.jpg",
    }
    paths = []

    def remote(path, **params):
        paths.append(path)
        if path == "search/movie":
            return {"results": [movie]}
        assert path == "movie/10"
        return {
            **movie,
            "runtime": 90,
            "videos": {
                "results": [
                    {
                        "site": "YouTube",
                        "type": "Trailer",
                        "official": True,
                        "key": "abcdefghijk",
                    }
                ]
            },
        }

    monkeypatch.setattr("backend.chat_tools.tmdb_get", remote)
    first = client.post(
        "/api/chat", json={"message": "Find Verified Journey", "session_id": "e2e-adk"}
    )
    assert first.status_code == 200
    assert first.json()["movies"][0]["title"] == "Verified Journey"
    assert db.get(Movie, 10).title == "Verified Journey"
    second = client.post(
        "/api/chat",
        json={
            "message": "How long is that film?",
            "session_id": "e2e-adk",
            "selected_movie_id": 10,
        },
    )
    assert second.status_code == 200
    assert (
        second.json()["movies"][0]["trailer_url"]
        == "https://www.youtube.com/watch?v=abcdefghijk"
    )
    assert "90" in second.json()["movies"][0]["reason"]
    assert db.get(Movie, 10).runtime == 90
    assert paths == ["search/movie", "movie/10"]
    followup_texts = [p.text for c in seen[2] for p in c.parts or [] if p.text]
    assert "Find Verified Journey" in followup_texts
    assert any("A verified journey." in text for text in followup_texts)
