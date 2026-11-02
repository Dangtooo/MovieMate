"""Session chat orchestration, deterministic follow-ups and grounded responses."""

import re

import httpx
from fastapi import HTTPException

from .ai import resolve_provider
from .chat_agent import run_agent
from .chat_tools import MovieTools, snapshot
from .models import Movie
from .preference_rules import describe_preferences, normalize, rules_preferences, split_title_year
from .schemas import ChatIn, ChatMovieCard, Preferences
from .tmdb import save_movies, tmdb_get
from .chat_metadata import KEYWORD_TRANSLATIONS
from .query_policy import sort_cards


def fallback_call(tools, message):
    state = tools.state
    prefs = state.preferences
    text = normalize(message)
    title = requested_title(message, state)
    if re.search(r"\b(o dau|xem tren|noi xem|nen tang|netflix|watch provider|streaming|thue phim|mua phim)\b", text):
        if not title:
            return {"reply": "Bạn muốn tra nơi xem của phim nào? Cho mình tên phim nhé.", "movies": []}
        country = country_for(text)
        return tools.execute("get_movie_watch_providers", {"movie_title": title, "country_code": country})
    if re.search(r"\b(trailer|thong tin|chi tiet|noi dung|thoi luong|do tuoi|ai dao dien|ai dong)\b|\b(?:dao dien|dien vien).*\b(?:la ai|gom ai)\b", text):
        if not title:
            return {"reply": "Bạn muốn tra thông tin hoặc trailer của phim nào? Cho mình tên phim nhé.", "movies": []}
        return tools.execute("get_movie_full_details", {"movie_title": title, "region": country_for(text)})
    categories = [
        ("now_playing", r"dang chieu|chieu rap hien tai|now playing"),
        ("upcoming", r"sap chieu|sap ra rap|upcoming"),
        ("trending", r"thinh hanh|trending|hot nhat"),
        ("top_rated", r"top rated|phim diem cao|phim duoc danh gia cao"),
    ]
    for category, pattern in categories:
        if re.search(r"\b(?:" + pattern + r")\b", text):
            return tools.execute("get_trending_or_cinema_movies", {"category": category,
                                 "time_window": "day" if "hom nay" in text else "week", "region": country_for(text)})
    if prefs.reference_title:
        return tools.execute("get_similar_and_recommended_movies", {"movie_title": prefs.reference_title, "year": prefs.reference_year})
    person = re.search(r"\b(?:do|cua)\s+(.+?)\s+dao dien\b", text)
    person = person or re.search(r"\b(?:dao dien|dien vien|phim cua|phim co|starring|actor|directed by)\s+(.+)", text)
    if person:
        raw = message[person.start(1):person.end(1)].rstrip(" .!?")
        prefix = re.match(r"(?:dao dien|dien vien)\s+", normalize(raw))
        if prefix:
            raw = raw[prefix.end():]
        end = re.search(r"\s+(?:dong chinh|dong phim|cung dong|nam\s+\d{4})\b|,\s*(?:duoi|tren|tu nam|diem|khong|the loai)\b", normalize(raw))
        if end:
            raw = raw[:end.start()]
        names = [n.strip() for n in re.split(r"\s+(?:và|va|and|cùng|cung|&)\s+|,", raw, flags=re.I) if n.strip()]
        return tools.execute("search_movies_by_people", {"person_names": names, "role": "director" if re.search(r"dao dien|directed by", text) else "actor"})
    named = re.search(r"\b(?:phim ten|tim ten phim|search movie)\s+(.+)", text)
    if named:
        return tools.execute("search_movie_by_title", {"query": message[named.start(1):].strip(" .!?\"'")})
    keywords = [english for term, english in KEYWORD_TRANSLATIONS.items() if
                re.search(r"\b" + re.escape(term) + r"\b", text) or re.search(r"\b" + re.escape(english) + r"\b", text)]
    if keywords:
        return tools.execute("discover_movies", {"keywords_text": ", ".join(dict.fromkeys(keywords))})
    if not describe_preferences(prefs) and not re.search(r"\b(phim|goi y|de xuat|recommend|xem gi|newer)\b", text):
        return {"reply": "Bạn muốn xem thể loại gì, phim của diễn viên nào hoặc phim tương tự bộ nào? Mình cần thêm một chút thông tin để tìm đúng nhé.", "movies": []}
    return tools.execute("discover_movies", {})


def country_for(text):
    for pattern, code in [(r"\b(my|hoa ky|united states|usa|us)\b", "US"),
                          (r"\b(anh quoc|united kingdom|uk|gb)\b", "GB"),
                          (r"\b(nhat ban|japan|jp)\b", "JP"), (r"\b(han quoc|korea|kr)\b", "KR")]:
        if re.search(pattern, text):
            return code
    return "VN"


def requested_title(message, state):
    text = normalize(message)
    quoted = re.search(r'["“](.+?)["”]', message)
    if quoted:
        return quoted[1]
    if re.search(r"\b(trong so do|trong danh sach|cac phim (?:do|nay)|bo nao|phim nao|of those|of them|any of them)\b", text):
        return None
    after = re.search(r"\b(?:phim|movie)\s+(?!nao\b|do\b|nay\b|vua\b|co\b)(.+)", text)
    if not after:
        after = re.search(r"\b(?:trailer cua|thong tin ve|noi dung cua)\s+(.+)", text)
    if after:
        rest = message[after.start(1):]
        end = re.search(r"\b(?:xem o dau|o dau|co trailer|la ai|gom ai|tren netflix|tai viet nam|o viet nam|tai my|o my|giup|nhe)\b|[?!]", normalize(rest))
        title = rest[:end.start()] if end else rest
        title = title.strip(" .,:!?")
        if title:
            return title
    before = re.search(r"\s+(?:co trailer|xem o dau|thoi luong bao lau)\b", text)
    if before and before.start() > 0:
        title = message[:before.start()].strip(" .!?")
        if normalize(title) not in {"no", "phim do", "bo do", "cac phim do"}:
            return title
    if len(state.last_ids) == 1 and state.last_ids[0] in state.evidence:
        return state.evidence[state.last_ids[0]]["title"]
    return None


def previous_trailers(tools, message):
    state = tools.state
    text = normalize(message)
    if "trailer" not in text or not state.last_ids or requested_title(message, state):
        return None
    if state.pending:
        return {"reply": "Bạn chọn đúng phim đang cần tra cứu trước nhé.", "movies": []}
    movies, lines = [], []
    for mid in state.last_ids[:5]:
        known = state.evidence[mid]
        state.selected_titles[normalize(known["title"])] = {"id": mid, "year": int(known["release_year"]) if known["release_year"] else None}
        result = tools.execute("get_movie_full_details", {"movie_title": known["title"]})
        card = next((m for m in result["movies"] if m["id"] == mid), None)
        if card:
            movies.append(card)
            lines.append(card["title"] + (": có trailer YouTube chính thức." if card["trailer_url"] else ": TMDB chưa có trailer chính thức có thể xác minh."))
        else:
            lines.append(known["title"] + ": chưa tra cứu được thông tin trailer.")
    return {"reply": "\n".join(lines), "movies": movies, "comparison": True}


def compare_previous(db, state, text):
    if re.search(r"\b(ngan nhat|shortest)\b", text):
        field, descending, label = "runtime", False, "thời lượng ngắn nhất"
    elif re.search(r"\b(moi nhat|newest|latest)\b", text):
        field, descending, label = "release_year", True, "năm phát hành mới nhất"
    elif re.search(r"\b(diem cao nhat|danh gia cao nhat|highest rated|best rated)\b", text):
        field, descending, label = "rating", True, "điểm TMDB cao nhất"
    else:
        return None
    previous_reference = re.search(r"\b(trong so|trong danh sach|vua goi y|of those|of them|those|these|o tren)\b", text)
    short_comparison = re.fullmatch(
        r"(?:(?:phim|bo)(?: nao)?|which(?: one)?(?: is)?|the)?\s*(?:ngan nhat|shortest|moi nhat|newest|latest|diem cao nhat|danh gia cao nhat|highest rated|best rated)(?:\s+(?:nhe|vay|the))?", text)
    if not previous_reference and not short_comparison:
        return None
    if not state.last_ids and not previous_reference and field != "runtime":
        return None
    if state.pending:
        return {"reply": "Bạn chọn đúng phim tham chiếu trước nhé, rồi mình sẽ so sánh các gợi ý cho bạn.", "movies": []}
    previous = [state.evidence[mid].copy() for mid in state.last_ids if mid in state.evidence]
    if not previous:
        return {"reply": "Mình chưa có danh sách phim nào trong hội thoại này để so sánh. Bạn muốn mình tìm phim gì trước?", "movies": []}
    if field == "runtime":
        for movie in previous:
            if not movie.get("runtime"):
                try:
                    detail = tmdb_get(f"movie/{movie['id']}", append_to_response="credits,videos")
                    save_movies(db, [detail], details=True)
                    updated = snapshot(db.get(Movie, movie["id"]))
                    movie.update(updated)
                    state.evidence[movie["id"]].update(updated)
                except HTTPException:
                    pass
    known = [m for m in previous if m.get(field)]
    if not known:
        return {"reply": "TMDB chưa cung cấp đủ dữ liệu để so sánh tiêu chí này. Mình không muốn đoán sai cho bạn.", "movies": []}
    best_value = (max if descending else min)(m[field] for m in known)
    winners = [m for m in known if m[field] == best_value]
    for movie in winners:
        value = f"{best_value} phút" if field == "runtime" else f"{best_value}/10" if field == "rating" else best_value
        movie["reason"] = f"Có {label} trong các phim vừa gợi ý: {value}."
    qualifier = "Trong số phim đã có dữ liệu đầy đủ" if len(known) < len(previous) else "Trong danh sách mình vừa gợi ý"
    return {"reply": qualifier + f", đây là phim có {label}.", "movies": winners[:5], "comparison": True}


def respond(db, state, payload, user_id):
    text = normalize(payload.message).strip(" .!?")
    if re.search(r"\b(bat dau lai|lam lai tu dau|bo het dieu kien|xoa tieu chi)\b", text):
        state.turns.clear()
        state.preferences = Preferences()
        state.evidence.clear()
        state.last_ids.clear()
        state.shown_ids.clear()
        state.pending.clear()
        state.pending_action.clear()
        state.selected_titles.clear()
        state.tool_options.clear()
    state.preferences = rules_preferences(ChatIn(message=payload.message, context=state.preferences))
    if re.search(r"\b(?:dao dien|dien vien|phim cua|phim co|starring|actor|directed by)\b", text):
        state.preferences.reference_title = state.preferences.reference_year = state.preferences.reference_movie_id = None
        state.pending.clear()
        state.pending_action.clear()
    if re.search(r"\b(bo gioi han diem|khong gioi han diem)\b", text):
        state.tool_options.pop("min_rating", None)
    rating = re.search(r"\b(?:diem(?: tmdb)?|rating)\s*(?:tu|tren|toi thieu|>=|at least)?\s*(\d+(?:[.,]\d+)?)", text)
    rating = rating or re.search(r"\b(?:tren|tu|toi thieu|at least)\s+(\d+(?:[.,]\d+)?)\s*diem\b", text)
    if rating and 0 <= float(rating[1].replace(",", ".")) <= 10:
        state.tool_options["min_rating"] = float(rating[1].replace(",", "."))
    provider = resolve_provider(payload.provider)
    mode, notice = "rules", None
    tools = MovieTools(db, state, user_id, payload.message)
    if payload.selected_movie_id is not None:
        choice = state.pending.get(payload.selected_movie_id)
        if not choice:
            result = {"reply": "Lựa chọn này không thuộc danh sách phim mình vừa tìm. Bạn tìm lại phim gốc để chọn nhé.", "movies": []}
        else:
            action = state.pending_action.copy()
            arguments = action.get("arguments", {}).copy()
            for title in (choice["title"], choice["original_title"], arguments.get("movie_title", "")):
                clean, _ = split_title_year(title)
                state.selected_titles[normalize(clean)] = {"id": choice["tmdb_id"], "year": choice["year"]}
            arguments["year"] = choice["year"]
            result = tools.execute(action.get("tool", "get_similar_and_recommended_movies"), arguments)
    elif text in {"chao", "xin chao", "hello", "hi", "chao ban"}:
        result = {"reply": "Chào bạn! Bạn muốn phim thuộc thể loại nào, của diễn viên nào hoặc tương tự bộ phim nào?", "movies": []}
    elif text in {"cam on", "cam on ban", "thanks", "ok", "okay"}:
        result = {"reply": "Rất vui được giúp bạn! Bạn có thể hỏi phim nào ngắn nhất, tìm phim mới hơn hoặc yêu cầu phim khác nhé.", "movies": []}
    else:
        year_answer = re.fullmatch(r"(?:(?:ban|phim)\s+)?(?:nam\s+)?\(?((?:19|20)\d{2}|2100)\)?", text)
        if state.pending_action and year_answer:
            arguments = {**state.pending_action["arguments"], "year": int(year_answer[1])}
            result = tools.execute(state.pending_action["tool"], arguments)
        else:
            result = previous_trailers(tools, payload.message)
        new_lookup = re.search(r"\b(dang chieu|sap chieu|thinh hanh|trending|top rated|thong tin|noi dung|trailer|xem o dau|noi xem|netflix)\b", text)
        if not state.last_ids and re.search(r"\b(diem cao nhat|danh gia cao nhat)\b", text) and not re.search(r"\b(trong so|trong danh sach)\b", text):
            new_lookup = True
        if result is None and not new_lookup:
            result = compare_previous(db, state, text)
        if result is None:
            if re.search(r"\b(moi hon|newer|more recent)\b", text):
                years = [int(state.evidence[mid]["release_year"]) for mid in state.last_ids
                         if mid in state.evidence and state.evidence[mid].get("release_year")]
                if not years:
                    result = {"reply": "Bạn muốn phim mới hơn năm nào? Mình chưa có mốc năm để so sánh trong hội thoại này.", "movies": []}
                else:
                    state.preferences.min_year = min(2100, max(years) + 1)
                    if state.preferences.max_year and state.preferences.max_year < state.preferences.min_year:
                        state.preferences.max_year = None
            if result is None:
                try:
                    if provider == "rules":
                        result = fallback_call(tools, payload.message)
                    else:
                        result, mode = run_agent(provider, state, payload.message, tools)
                except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError):
                    mode = "rules_fallback"
                    notice = ("Qwen local" if provider == "ollama" else "Gemini") + " chưa xử lý được yêu cầu. Đang dùng dữ liệu từ công cụ TMDB và bộ lọc dự phòng."
                    result = tools.result or fallback_call(tools, payload.message)
    action = result.get("action", "recommendations")
    if action != "choose-reference" and not result.get("comparison"):
        result["movies"] = sort_cards(result["movies"], state.preferences.sort_by)
    result["movies"] = result["movies"][:8 if action == "choose-reference" else 5]
    if result["movies"] and action != "choose-reference":
        for movie in result["movies"]:
            state.evidence[movie["id"]] = movie.copy()
        if not result.get("comparison"):
            state.last_ids = [m["id"] for m in result["movies"]]
        state.shown_ids = list(dict.fromkeys(state.shown_ids + [m["id"] for m in result["movies"]]))[-100:]
        keep = set(state.shown_ids + state.last_ids)
        state.evidence = {mid: m for mid, m in state.evidence.items() if mid in keep}
    state.turns.append({"role": "user", "content": payload.message})
    summary = result["reply"][:600] + "\nPhim: " + "; ".join(
        f"{m['title']} ({m['release_year']})" for m in result["movies"])
    state.turns.append({"role": "assistant", "content": summary[:1200]})
    cards = [ChatMovieCard.model_validate(movie).model_dump() for movie in result["movies"]]
    return {"reply": result["reply"], "movies": cards}, {"mode": mode, "notice": notice, "action": action}
