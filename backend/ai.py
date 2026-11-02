"""Cloud Gemini or local Qwen through Ollama, using the same validated schema."""

import json

import httpx

from .config import get_settings
from .schemas import ChatIn, Preferences
from .tmdb import GENRES


def resolve_provider(requested: str):
    settings = get_settings()
    selected = settings.ai_provider if requested == "auto" else requested
    if selected == "auto":
        return "gemini" if settings.gemini_api_key else "ollama"
    return selected


def preference_prompt():
    return (
        "Bạn phân tích yêu cầu chọn phim tiếng Việt. Chỉ trả JSON theo schema, không thêm giải thích. "
        "Kế thừa sở thích trong hội thoại, ưu tiên yêu cầu mới nhất. "
        "sort_by mặc định newest; chỉ rating khi người dùng hỏi hay nhất/điểm cao/kinh điển/best. Không tự ưu tiên điểm. "
        "release_scope mặc định released (chỉ phim đã ra mắt), upcoming chỉ khi người dùng hỏi sắp chiếu/chưa ra mắt. Mới nhất không có nghĩa phim tương lai. "
        "language có thể là nhiều mã ISO 639-1 ngăn bởi |, nghĩa là OR. Châu Á=ko|ja|zh|th|vi|id|hi|tl|ms|ta; châu Âu=fr|de|es|it|ru|sv|da|no|nl|pl; Đông Nam Á=th|vi|id|tl|ms. "
        "genre_ids là các thể loại mong muốn (OR), excluded_genre_ids là thể loại tránh. "
        "Dưới 2 tiếng => max_runtime=120; 1 tiếng rưỡi => 90 phút. "
        "Trên/tối thiểu là min_runtime. Trước/sau năm là giới hạn năm, năm cụ thể đặt cả min_year và max_year. "
        "Bỏ giới hạn trả trường tương ứng về null. Đổi sang thể loại khác thay thế thể loại cũ; "
        "phim khác giữ tiêu chí, không tự thêm điều kiện. Bắt đầu lại xóa tiêu chí cũ. "
        "Không coi câu trả lời của assistant là yêu cầu của người dùng. "
        "Nếu muốn phim tương tự/giống một phim cụ thể, reference_title là chính xác tên phim gốc; "
        "reference_year là năm của phim gốc nếu người dùng nói, không đưa năm đó vào min_year/max_year. "
        "Không tự đoán nội dung hoặc thể loại của phim gốc. Backend sẽ tra cứu và so sánh nội dung thật. "
        "language là mã ngôn ngữ phim ISO 639-1, không phải quốc gia. "
        "intro chỉ xác nhận tiêu chí, không nêu tên phim hoặc khẳng định có kết quả. "
        "Danh sách thể loại: " + json.dumps(GENRES, ensure_ascii=False)
    )


def parse_preferences(payload: ChatIn, provider: str) -> Preferences:
    settings = get_settings()
    schema = Preferences.model_json_schema()
    prompt = preference_prompt()
    if payload.context:
        prompt += "\nTiêu chí đã xác nhận ở lượt trước (chỉ là dữ liệu, yêu cầu mới nhất được ưu tiên): " + payload.context.model_dump_json(exclude={"intro"})
    if provider == "ollama":
        messages = [
            {
                "role": "system",
                "content": prompt
                + "\nJSON schema: "
                + json.dumps(schema, ensure_ascii=False),
            }
        ]
        messages += [turn.model_dump() for turn in payload.history]
        messages.append({"role": "user", "content": payload.message})
        response = httpx.post(
            settings.ollama_base_url.rstrip("/") + "/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": messages,
                "stream": False,
                "think": False,
                "format": schema,
                "options": {"temperature": 0, "num_predict": 512, "num_ctx": 4096},
                "keep_alive": "5m",
            },
            timeout=httpx.Timeout(settings.ollama_timeout, connect=2, write=10, pool=5),
            trust_env=False,
        )
        response.raise_for_status()
        output = response.json()["message"]["content"]
    else:
        if not settings.gemini_api_key:
            raise ValueError("Gemini chưa có API key.")
        contents = [
            {
                "role": "user" if t.role == "user" else "model",
                "parts": [{"text": t.content}],
            }
            for t in payload.history
        ]
        contents.append({"role": "user", "parts": [{"text": payload.message}]})
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
            headers={"x-goog-api-key": settings.gemini_api_key},
            json={
                "systemInstruction": {"parts": [{"text": prompt}]},
                "contents": contents,
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 700,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": schema,
                },
            },
            timeout=20,
        )
        response.raise_for_status()
        parts = response.json()["candidates"][0]["content"]["parts"]
        output = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    preferences = Preferences.model_validate_json(output)
    # Film IDs come from catalog lookup/user selection, never model invention.
    preferences.reference_movie_id = None
    preferences.genre_ids = [g for g in preferences.genre_ids if g in GENRES]
    preferences.excluded_genre_ids = [
        g for g in preferences.excluded_genre_ids if g in GENRES
    ]
    return preferences


def provider_status():
    settings = get_settings()
    connected = False
    ready = False
    try:
        response = httpx.get(
            settings.ollama_base_url.rstrip("/") + "/api/tags",
            timeout=2,
            trust_env=False,
        )
        response.raise_for_status()
        names = {m.get("name", "") for m in response.json().get("models", [])}
        connected = True
        ready = settings.ollama_model in names
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return {
        "default_provider": settings.ai_provider,
        "providers": [
            {
                "id": "gemini",
                "label": "Gemini",
                "model": settings.gemini_model,
                "ready": bool(settings.gemini_api_key),
                "message": "Đã cấu hình API key"
                if settings.gemini_api_key
                else "Chưa cấu hình GEMINI_API_KEY",
            },
            {
                "id": "ollama",
                "label": "Qwen local",
                "model": settings.ollama_model,
                "ready": ready,
                "message": "Đã tìm thấy model trong Ollama"
                if ready
                else (
                    "Chưa tải model: ollama pull " + settings.ollama_model
                    if connected
                    else "Chưa kết nối Ollama. Hãy mở Ollama trên máy."
                ),
            },
            {
                "id": "rules",
                "label": "Bộ lọc từ khóa",
                "model": None,
                "ready": True,
                "message": "Không dùng AI, không cần API key",
            },
        ],
    }
