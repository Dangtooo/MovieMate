"""HTTP contract, cookie ownership and safe failure behavior of ADK chat."""

import pytest
from google.adk.agents.invocation_context import LlmCallsLimitExceededError

from backend import chat_service
from backend.chat_agent import AgentAnswer, OutputTokenLimitError
from backend.config import get_settings


@pytest.mark.parametrize(
    "patch",
    [
        {"session_id": None},
        {"session_id": ""},
        {"session_id": "a" * 129},
        {"session_id": "../other-session"},
        {"message": "  "},
        {"message": "x" * 1001},
        {"provider": "ollama"},
        {"selected_movie_id": 0},
        {"selected_movie_id": -1},
    ],
)
def test_invalid_chat_request_never_invokes_agent(client, monkeypatch, patch):
    def unexpected(*args):
        pytest.fail("Invalid payload reached chat processing.")

    monkeypatch.setattr("backend.main.respond", unexpected)
    response = client.post(
        "/api/chat", json={"message": "Hello", "session_id": "valid-id", **patch}
    )
    assert response.status_code == 422


def test_chat_json_contract_headers_and_missing_session(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "fake-test-key")

    async def fake(state, message, tools):
        tools.evidence[862] = {
            "id": 862,
            "title": "Toy Story",
            "release_date": "1995-11-22",
            "vote_average": 8.0,
        }
        return AgentAnswer(reply="Verified title.", movie_ids=[862])

    monkeypatch.setattr(chat_service, "run_agent", fake)
    assert client.post("/api/chat", json={"message": "Hello"}).status_code == 422
    response = client.post(
        "/api/chat", json={"message": "Find a film", "session_id": "contract"}
    )
    assert response.status_code == 200
    assert set(response.json()) == {"reply", "movies"}
    assert set(response.json()["movies"][0]) == {
        "id",
        "title",
        "release_year",
        "rating",
        "poster_url",
        "trailer_url",
        "reason",
    }
    assert response.headers["x-chat-provider"] == "gemini"
    assert response.headers["x-chat-action"] == "recommendations"
    assert "x-chat-notice" not in response.headers


def test_tampering_guest_cookie_does_not_reuse_another_conversation(
    client, monkeypatch
):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "fake-test-key")
    histories = []

    async def fake(state, message, tools):
        histories.append(len(state.turns))
        return AgentAnswer(reply="Hello", movie_ids=[])

    monkeypatch.setattr(chat_service, "run_agent", fake)
    payload = {"message": "Hello", "session_id": "shared-name"}
    first = client.post("/api/chat", json=payload)
    cookie = client.cookies.get(chat_service.COOKIE)
    assert "HttpOnly" in first.headers["set-cookie"]
    assert "SameSite=lax" in first.headers["set-cookie"]
    client.post("/api/chat", json=payload)
    client.cookies.clear()
    token, signature = cookie.split(".")
    modified = token + "." + ("0" if signature[0] != "0" else "1") + signature[1:]
    client.cookies.set(chat_service.COOKIE, modified)
    client.post("/api/chat", json=payload)
    assert histories == [0, 2, 0]


def test_login_changes_owner_and_logout_restores_guest_history(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "fake-test-key")
    histories = []

    async def fake(state, message, tools):
        histories.append([turn["content"] for turn in state.turns])
        return AgentAnswer(reply="OK", movie_ids=[])

    monkeypatch.setattr(chat_service, "run_agent", fake)
    payload = {"message": "Guest preference", "session_id": "same-session"}
    client.post("/api/chat", json=payload)
    assert (
        client.post(
            "/api/auth/register",
            json={
                "name": "Test Viewer",
                "email": "owner@example.com",
                "password": "test-password-123",
            },
        ).status_code
        == 201
    )
    client.post("/api/chat", json={**payload, "message": "Private account preference"})
    client.post("/api/auth/logout")
    client.post("/api/chat", json=payload)
    assert histories[0] == [] and histories[1] == []
    assert histories[2][0] == "Guest preference"
    assert "Private account preference" not in histories[2]


def test_selected_movie_must_belong_to_last_results(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "fake-test-key")
    seen = []

    async def fake(state, message, tools):
        seen.append(message)
        tools.evidence[862] = {"id": 862, "title": "Toy Story"}
        return AgentAnswer(reply="A film", movie_ids=[862])

    monkeypatch.setattr(chat_service, "run_agent", fake)
    payload = {"message": "Films please", "session_id": "selection"}
    client.post("/api/chat", json=payload)
    bad = client.post("/api/chat", json={**payload, "selected_movie_id": 999})
    assert bad.status_code == 400 and len(seen) == 1
    good = client.post("/api/chat", json={**payload, "selected_movie_id": 862})
    assert good.status_code == 200
    assert "Toy Story" in seen[1] and "862" in seen[1]


@pytest.mark.parametrize(
    "error,status,fragment",
    [
        (TimeoutError("private-error-message"), 504, "chậm"),
        (LlmCallsLimitExceededError("private-error-message"), 502, "nhiều bước"),
        (OutputTokenLimitError("private-error-message"), 502, "cắt"),
        (ValueError("private-error-message"), 502, "định dạng"),
        (RuntimeError("private-error-message"), 502, "kết nối"),
    ],
)
def test_failed_turn_does_not_commit_history_and_can_be_retried(
    client, monkeypatch, caplog, error, status, fragment
):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "fake-test-key")

    async def broken(state, message, tools):
        raise error

    monkeypatch.setattr(chat_service, "run_agent", broken)
    payload = {"message": "Find a film", "session_id": "retry-after-failure"}
    failed = client.post("/api/chat", json=payload)
    assert failed.status_code == status
    assert fragment in failed.json()["detail"]
    assert "private-error-message" not in failed.text + caplog.text

    async def recovered(state, message, tools):
        assert not state.turns
        return AgentAnswer(reply="Recovered", movie_ids=[])

    monkeypatch.setattr(chat_service, "run_agent", recovered)
    assert client.post("/api/chat", json=payload).json()["reply"] == "Recovered"


def test_long_conversation_bounds_memory_and_retains_selected_evidence(db, monkeypatch):
    from backend.chat_service import Conversation
    from backend.schemas import ChatRequest

    monkeypatch.setattr(get_settings(), "gemini_api_key", "fake-test-key")

    async def fake(state, message, tools):
        tools.evidence.update(
            {i: {"id": i, "title": f"Film {i}"} for i in range(1, 81)}
        )
        return AgentAnswer(reply="x" * 5000, movie_ids=[1])

    monkeypatch.setattr(chat_service, "run_agent", fake)
    state = Conversation()
    for i in range(12):
        chat_service.respond(
            db, state, ChatRequest(message=f"user-turn-{i}", session_id="bounded"), None
        )
    assert len(state.turns) == 16
    assert state.turns[0]["content"] == "user-turn-4"
    assert len(state.turns[-1]["content"]) < 3100
    assert len(state.evidence) == 60
    assert 1 in state.evidence and state.last_ids == [1]
