"""Session lifecycle checks, with a fake clock instead of real sleeps."""

import pytest
from fastapi import HTTPException

from backend import chat_service
from backend.chat_service import ConversationStore


def test_expired_session_loses_history_but_recent_session_survives(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(chat_service, "monotonic", lambda: clock[0])
    monkeypatch.setattr(chat_service, "TTL", 10)
    store = ConversationStore()
    with store.acquire("guest", "old") as state:
        state.turns.append({"role": "user", "content": "Old preference"})
    clock[0] = 105
    with store.acquire("guest", "recent") as state:
        state.last_ids = [862]
    clock[0] = 110
    with store.acquire("guest", "old") as state:
        assert not state.turns
    with store.acquire("guest", "recent") as state:
        assert state.last_ids == [862]


def test_expiry_does_not_evict_an_inflight_turn(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(chat_service, "monotonic", lambda: clock[0])
    monkeypatch.setattr(chat_service, "TTL", 10)
    store = ConversationStore()
    with store.acquire("owner", "working") as original:
        clock[0] += 11
        with store.acquire("other", "new"):
            assert store.items[("owner", "working")] is original
        with pytest.raises(HTTPException) as error:
            with store.acquire("owner", "working"):
                pass
        assert error.value.status_code == 409


def test_lock_is_released_when_processing_fails():
    store = ConversationStore()
    with pytest.raises(RuntimeError, match="tool failed"):
        with store.acquire("owner", "turn"):
            raise RuntimeError("tool failed")
    with store.acquire("owner", "turn") as state:
        state.last_ids = [862]
    with store.acquire("owner", "turn") as state:
        assert state.last_ids == [862]


def test_owner_limit_evicts_least_recently_used_unlocked_session(monkeypatch):
    monkeypatch.setattr(chat_service, "MAX_PER_OWNER", 2)
    store = ConversationStore()
    for sid in ["first", "second", "first", "third"]:
        with store.acquire("owner", sid):
            pass
    assert ("owner", "first") in store.items
    assert ("owner", "second") not in store.items
    assert ("owner", "third") in store.items


def test_global_limit_preserves_locked_session_and_evicts_idle_one(monkeypatch):
    monkeypatch.setattr(chat_service, "MAX_SESSIONS", 2)
    store = ConversationStore()
    with store.acquire("a", "locked") as working:
        with store.acquire("b", "idle"):
            pass
        with store.acquire("c", "new"):
            assert store.items[("a", "locked")] is working
            assert ("b", "idle") not in store.items


@pytest.mark.parametrize("limit", ["MAX_PER_OWNER", "MAX_SESSIONS"])
def test_full_store_rejects_new_turn_if_every_slot_is_busy(monkeypatch, limit):
    monkeypatch.setattr(chat_service, limit, 1)
    store = ConversationStore()
    with store.acquire("owner", "locked") as state:
        with pytest.raises(HTTPException) as error:
            with store.acquire("owner", "new"):
                pass
        assert error.value.status_code == 503
        assert store.items[("owner", "locked")] is state
