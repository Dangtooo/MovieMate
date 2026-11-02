"""Bounded, expiring conversation memory. One writer per browser/session pair."""

import asyncio
import json
import logging
import hashlib
import hmac
import secrets
from collections import OrderedDict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic

from fastapi import HTTPException
from google.adk.agents.invocation_context import LlmCallsLimitExceededError
from google.genai.errors import APIError
from pydantic import ValidationError

from .chat_agent import OutputTokenLimitError, run_agent
from .chat_tools import MovieTools, movie_card, watched_movies
from .config import get_settings
from .schemas import ChatMovieCard

COOKIE = "moviemate_chat_owner"
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
        response.set_cookie(
            COOKIE,
            token + "." + signature,
            httponly=True,
            secure=get_settings().cookie_secure,
            samesite="lax",
            max_age=TTL,
        )
    return "guest:" + token


@dataclass
class Conversation:
    turns: deque = field(default_factory=lambda: deque(maxlen=16))
    evidence: dict = field(default_factory=dict)
    last_ids: list = field(default_factory=list)
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
                owned = [k for k in self.items if k[0] == owner]
                if len(owned) >= MAX_PER_OWNER:
                    removable = next(
                        (k for k in owned if not self.items[k].lock.locked()), None
                    )
                    if removable is None:
                        raise HTTPException(
                            503, "Bạn đang có quá nhiều hội thoại được xử lý."
                        )
                    del self.items[removable]
                while len(self.items) >= MAX_SESSIONS:
                    removable = next(
                        (k for k, v in self.items.items() if not v.lock.locked()), None
                    )
                    if removable is None:
                        raise HTTPException(503, "Chat đang bận, bạn thử lại sau nhé.")
                    del self.items[removable]
                self.items[key] = Conversation()
            item = self.items[key]
            if not item.lock.acquire(blocking=False):
                raise HTTPException(
                    409, "Câu hỏi trước đang được xử lý. Bạn chờ một chút nhé."
                )
            item.touched = now
            self.items.move_to_end(key)
        try:
            yield item
        finally:
            item.touched = monotonic()
            item.lock.release()


conversations = ConversationStore()


logger = logging.getLogger(__name__)


def provider_status():
    settings = get_settings()
    return {
        "default_provider": "gemini",
        "providers": [
            {
                "id": "gemini",
                "label": "Gemini · Google ADK",
                "model": settings.gemini_model,
                "ready": bool(settings.gemini_api_key),
                "message": (
                    "Đã cấu hình Gemini cho Google ADK"
                    if settings.gemini_api_key
                    else "Chưa cấu hình GEMINI_API_KEY"
                ),
            }
        ],
    }


def respond(db, state, payload, user_id):
    settings = get_settings()
    if not settings.gemini_api_key:
        raise HTTPException(
            503, "Hãy cấu hình GEMINI_API_KEY trong .env để dùng chatbot Google ADK."
        )
    tools = MovieTools(db, state.evidence, watched_movies(db, user_id))
    message = payload.message
    if payload.selected_movie_id is not None:
        if payload.selected_movie_id not in state.last_ids:
            raise HTTPException(
                400, "Phim được chọn không thuộc danh sách vừa tra cứu."
            )
        chosen = state.evidence[payload.selected_movie_id]
        message += f"\nNgười dùng chọn phim đã xác minh: {chosen['title']} (TMDB {chosen['id']})."
    try:
        answer = asyncio.run(run_agent(state, message, tools))
    except APIError as exc:
        code = exc.code
        logger.warning("Gemini API failed (HTTP %s)", code)
        if code == 429:
            raise HTTPException(
                429,
                "Gemini đang giới hạn yêu cầu hoặc quota của project/model. Đổi key trong cùng project không tăng quota; kiểm tra Usage/Rate limits trong Google AI Studio.",
            ) from None
        if code in (401, 403):
            raise HTTPException(
                503,
                "Gemini từ chối API key hoặc quyền truy cập. Kiểm tra key và quyền của project.",
            ) from None
        if code == 404:
            raise HTTPException(
                503,
                "Không truy cập được model Gemini đã cấu hình. Kiểm tra GEMINI_MODEL rồi khởi động lại server.",
            ) from None
        raise HTTPException(
            502, "Dịch vụ Gemini trả lỗi. Vui lòng thử lại sau."
        ) from None
    except OutputTokenLimitError:
        raise HTTPException(
            502,
            "Gemini trả lời quá dài và bị cắt giữa chừng. Hãy chia câu hỏi nhỏ hơn; đây không phải lỗi hết quota API.",
        ) from None
    except LlmCallsLimitExceededError:
        raise HTTPException(
            502,
            "Câu hỏi cần quá nhiều bước tra cứu. Hãy thu hẹp yêu cầu; đây không phải lỗi hết token API.",
        ) from None
    except TimeoutError:
        raise HTTPException(
            504, "Gemini hoặc công cụ tra cứu phản hồi quá chậm. Vui lòng thử lại."
        ) from None
    except (ValidationError, ValueError):
        raise HTTPException(
            502,
            "Gemini trả phản hồi không đúng định dạng hoặc ID phim chưa xác minh. Hãy thử lại; đây không phải lỗi hết quota.",
        ) from None
    except Exception as exc:
        # Do not log exception messages: upstream errors can contain credentials.
        logger.warning("ADK request failed (%s)", type(exc).__name__)
        raise HTTPException(
            502, "Chatbot gặp lỗi xử lý hoặc kết nối. Vui lòng thử lại."
        ) from None
    ids = list(dict.fromkeys(answer.movie_ids))[:5]
    cards = [
        ChatMovieCard.model_validate(movie_card(tools.evidence[mid])).model_dump()
        for mid in ids
    ]
    state.turns.append({"role": "user", "content": message})
    state.turns.append(
        {
            "role": "assistant",
            "content": answer.reply[:3000] + "\nPhim: " + json.dumps(ids),
        }
    )
    keep = list(dict.fromkeys([mid for mid in tools.evidence if mid not in ids] + ids))[
        -60:
    ]
    state.evidence = {mid: tools.evidence[mid] for mid in keep}
    if ids:
        state.last_ids = ids
    return {"reply": answer.reply, "movies": cards}, {
        "mode": "gemini",
        "notice": None,
        "action": "recommendations",
    }
