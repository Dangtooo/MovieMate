"""Bounded, expiring conversation memory. One writer per browser/session pair."""

import hashlib
import hmac
import secrets
from collections import OrderedDict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic

from fastapi import HTTPException

from .config import get_settings
from .schemas import Preferences

COOKIE = "cine_chat_owner"
TTL = 3600
MAX_SESSIONS = 500
MAX_PER_OWNER = 8


def owner_for(request, response, user):
    if user:
        return f"user:{user.id}"
    cookie = request.cookies.get(COOKIE, "")
    token, _, signature = cookie.partition(".")
    key = get_settings().secret_key.encode()
    expected = hmac.new(key, token.encode(), hashlib.sha256).hexdigest()
    if not token or not hmac.compare_digest(signature.encode(), expected.encode()):
        token = secrets.token_urlsafe(24)
        signature = hmac.new(key, token.encode(), hashlib.sha256).hexdigest()
        response.set_cookie(COOKIE, token + "." + signature, httponly=True,
                            secure=get_settings().cookie_secure, samesite="lax", max_age=TTL)
    return "guest:" + token


@dataclass
class Conversation:
    turns: deque = field(default_factory=lambda: deque(maxlen=16))
    preferences: Preferences = field(default_factory=Preferences)
    evidence: dict = field(default_factory=dict)
    last_ids: list = field(default_factory=list)
    shown_ids: list = field(default_factory=list)
    pending: dict = field(default_factory=dict)
    pending_action: dict = field(default_factory=dict)
    selected_titles: dict = field(default_factory=dict)
    tool_options: dict = field(default_factory=dict)
    touched: float = field(default_factory=monotonic)
    lock: Lock = field(default_factory=Lock)


class ConversationStore:
    def __init__(self):
        self.items = OrderedDict()
        self.lock = Lock()

    @contextmanager
    def acquire(self, owner, session_id):
        key = (owner, session_id)
        with self.lock:
            now = monotonic()
            for old_key, item in list(self.items.items()):
                if now - item.touched >= TTL and not item.lock.locked():
                    del self.items[old_key]
            if key not in self.items:
                owned = [k for k, v in self.items.items() if k[0] == owner and not v.lock.locked()]
                if len(owned) >= MAX_PER_OWNER:
                    del self.items[owned[0]]
                while len(self.items) >= MAX_SESSIONS:
                    removable = next((k for k, v in self.items.items() if not v.lock.locked()), None)
                    if removable is None:
                        raise HTTPException(503, "Chat đang bận, bạn thử lại sau nhé.")
                    del self.items[removable]
                self.items[key] = Conversation()
            item = self.items[key]
            if not item.lock.acquire(blocking=False):
                raise HTTPException(409, "Câu hỏi trước đang được xử lý. Bạn chờ một chút nhé.")
            item.touched = now
            self.items.move_to_end(key)
        try:
            yield item
        finally:
            item.touched = monotonic()
            item.lock.release()


conversations = ConversationStore()
