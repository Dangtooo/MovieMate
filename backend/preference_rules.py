"""Deterministic Vietnamese preference updates, shared by rules and AI fallback."""

import re
import unicodedata

from .schemas import ChatIn, Preferences
from .tmdb import GENRES


def normalize(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", value.lower().replace("đ", "d"))
        if unicodedata.category(c) != "Mn"
    )


GENRE_TERMS = {
    28: ["hanh dong", "action"],
    35: ["hai", "comedy", "vui ve", "vui nhon"],
    27: ["kinh di", "horror"],
    9648: ["trinh tham", "bi an", "twist"],
    10749: ["lang man", "tinh cam", "romance"],
    878: ["khoa hoc vien tuong", "vien tuong", "sci-fi", "sci fi"],
    16: ["hoat hinh", "anime", "animation"],
    18: ["chinh kich", "cam dong", "drama"],
    10751: ["gia dinh"], 10752: ["chien tranh"],
    12: ["phieu luu"], 80: ["toi pham"], 99: ["tai lieu"],
    14: ["gia tuong", "fantasy"], 36: ["lich su"],
    10402: ["am nhac"], 53: ["giat gan", "thriller"], 37: ["cao boi"],
}
LANGUAGES = {
    "ko": ["han quoc", "phim han", "tieng han", "xu kim chi"],
    "ja": ["nhat ban", "phim nhat", "tieng nhat"],
    "vi": ["viet nam", "phim viet", "tieng viet"],
    "fr": ["phim phap", "tieng phap", "nuoc phap"],
    "hi": ["an do", "phim an", "tieng hindi", "bollywood"],
    "en": ["phim my", "phim anh", "tieng anh", "hollywood", "cua my", "nuoc my", "american"],
    "zh": ["trung quoc", "phim trung", "tieng trung", "hoa ngu", "hong kong", "dai loan"],
    "th": ["thai lan", "phim thai", "tieng thai"],
    "id": ["indonesia", "phim indo"],
    "es": ["tay ban nha", "phim tay ban nha", "tieng tay ban nha"],
    "de": ["phim duc", "nuoc duc", "tieng duc"],
    "it": ["phim y", "nuoc y", "tieng y"],
    "ko|ja|zh|th|vi|id|hi|tl|ms|ta": ["chau a", "a dong", "phim a", "asian", "asia"],
    "th|vi|id|tl|ms": ["dong nam a"],
    "fr|de|es|it|ru|sv|da|no|nl|pl": ["chau au", "phim au", "europe", "european"],
    "en|fr|de|es|it": ["au my", "phuong tay"],
    "es|pt": ["my latinh", "chua my", "chau my", "nam my"],
}


def requested_language(text):
    """Return (explicitly requested, OR language filter); corrections replace it."""
    text = normalize(text)
    if re.search(r"\b(ngon ngu nao cung duoc|nuoc nao cung duoc|khu vuc nao cung duoc|bo gioi han (?:ngon ngu|khu vuc)|khong gioi han (?:ngon ngu|khu vuc))\b", text):
        return True, None
    selected = None
    for clause in re.split(r"\b(?:nhung|doi sang|chuyen sang|thay bang|rieng|chi lay)\b", text):
        matches = sorted((m.start(), code) for code, terms in LANGUAGES.items() for term in terms
                         for m in re.finditer(r"\b" + re.escape(term) + r"\b", clause)
                         if not re.search(r"\b(?:khong(?: phai| thich| muon| xem)?|tranh|dung)\s*$", clause[:m.start()]))
        # Short country names after a conjunction, e.g. 'phim Hàn hoặc Nhật'.
        short = {"han": "ko", "nhat": "ja", "viet": "vi", "phap": "fr", "thai": "th", "trung": "zh", "duc": "de", "y": "it"}
        if matches:
            matches += [(m.start(), short[m[1]]) for m in re.finditer(
                r"\b(?:hoac|va|or|and)\s+(han|nhat|viet|phap|thai|trung|duc|y)\b", clause)]
        if matches:
            selected = "|".join(dict.fromkeys(code for _, codes in sorted(matches) for code in codes.split("|")))
    return selected is not None, selected


def requested_sort(text):
    """User text, never model defaults, controls the output ordering."""
    text = normalize(text)
    text = re.sub(r'["“].*?["”]', "", text)
    quality = r"diem cao|diem so|diem(?: tmdb)?\s*(?:(?:tu|tren|toi thieu|>=)\s*)?\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s*diem|rating|hay nhat|dinh nhat|xuat sac nhat|tot nhat|danh gia cao|chat luong cao|top(?!\s+gun\b)|kinh dien|best|highest rated|classics?"
    decisions = []
    for match in re.finditer(r"\b(?:" + quality + r")\b", text):
        prefix = text[max(0, match.start() - 45):match.start()]
        if not re.search(r"\b(?:khong(?: can| quan trong| uu tien)?|bo gioi han|dung)\s*(?:ve\s+|theo\s+)?$", prefix):
            decisions.append((match.start(), "rating"))
    decisions += [(m.start(), "newest") for m in re.finditer(r"\b(moi nhat|gan day|sap chieu|newest|latest|recent)\b", text)]
    return max(decisions, default=(0, "newest"))[1]


def wants_more(message: str) -> bool:
    return bool(re.search(r"\b(phim khac|bo khac|goi y khac|them phim|them vai|tiep tuc|doi phim)\b", normalize(message)))


def requested_release_scope(text, previous="released"):
    text = normalize(text)
    text = re.sub(r'["“].*?["”]', "", text)
    choices = []
    for match in re.finditer(r"\b(sap chieu|sap ra mat|chua ra mat|chua phat hanh|upcoming|unreleased|coming soon|not yet released)\b", text):
        prefix = text[max(0, match.start() - 30):match.start()]
        negated = re.search(r"\b(khong(?: lay| can| muon)?|dung|tranh)\s*(?:phim\s*)?$", prefix)
        choices.append((match.start(), "released" if negated else "upcoming"))
    choices += [(m.start(), "released") for m in re.finditer(
        r"\b(da ra mat|da phat hanh|da chieu|dang chieu|moi nhat|released|newest|latest)\b", text)
        if not re.search(r"not yet\s*$", text[:m.start()])]
    if choices:
        return max(choices)[1]
    continuation = wants_more(text) or re.search(r"^(duoi|tren|toi da|toi thieu|it nhat|bo gioi han|nuoc nao|ngon ngu nao|khu vuc nao|chi |them |tu nam|truoc nam|sau nam|cam on|hello|hi\b)", text)
    return previous if continuation else "released"


def split_title_year(value: str):
    """Only explicit year annotations are dates; 1917/Blade Runner 2049 are titles."""
    match = re.search(r"(?:\s*\(((?:19|20)\d{2}|2100)\)|\s+(?:năm|nam)\s+((?:19|20)\d{2}|2100))\s*$", value, re.I)
    if match and value[:match.start()].strip():
        return value[:match.start()].strip(), int(match[1] or match[2])
    return value.strip(), None


def extract_reference(message: str):
    """Extract the named film, keeping its year separate from release filters."""
    normalized = normalize(message)
    match = re.search(r"\b(?:tuong tu|giong(?: nhu)?|similar to|like)\s+(?:(?:bo phim|phim|movie)\s+)?", normalized)
    if not match:
        return None
    rest = message[match.end():]
    end = re.search(r"[,;!?]|\b(?:nhung|va phai|va tranh|duoi|tren|khong qua|giup|nhe|duoc khong)\b", normalize(rest))
    raw = rest[:end.start()] if end else rest
    raw = raw.strip(" \"'“”‘’.:")
    title, year = split_title_year(raw)
    title = title.strip(" \"'“”‘’")
    if not title or len(title) > 150:
        return None
    # Remove the title/year so words inside a movie name cannot become filters.
    criteria = message[:match.start()] + " " + (rest[end.start():] if end else "")
    return title, year, criteria


def rules_preferences(payload: ChatIn) -> Preferences:
    prefs = payload.context.model_copy(deep=True) if payload.context else Preferences()
    turns = [payload.message] if payload.context else [
        t.content for t in payload.history if t.role == "user"
    ] + [payload.message]
    for turn in turns:
        text = normalize(turn)
        if re.search(r"\b(bat dau lai|lam lai tu dau|bo het (?:dieu kien|tieu chi)|xoa (?:dieu kien|tieu chi))\b", text):
            prefs = Preferences()
        reference = extract_reference(turn)
        if reference:
            prefs.reference_title, prefs.reference_year, criteria = reference
            prefs.reference_movie_id = None
            text = normalize(criteria)
        elif prefs.reference_title:
            year_reply = re.fullmatch(r"\s*(?:(?:ban|phim)\s+)?(?:nam\s+)?\(?((?:19|20)\d{2}|2100)\)?[.!?\s]*", text)
            if year_reply:
                prefs.reference_year = int(year_reply[1])
                prefs.reference_movie_id = None
                text = ""
        if re.search(r"\b(bo phim tham chieu|khong can tuong tu|khong can giong)\b", text):
            prefs.reference_title = prefs.reference_year = None
            prefs.reference_movie_id = None
        prefs.sort_by = requested_sort(text)
        prefs.release_scope = requested_release_scope(text, prefs.release_scope)
        # Process clauses in order: a later correction wins, assistant text is never parsed.
        turn_wanted = False
        negative = False
        runtime_updated = set()
        for clause in re.split(r"[,;.!?]|\b(nhung|ma la|thay vao do|chuyen sang|doi sang)\b", text):
            if not clause:
                continue
            if clause in {"nhung", "ma la", "thay vao do", "chuyen sang", "doi sang"}:
                turn_wanted = False
                negative = False
                continue
            wanted, excluded = [], []
            matches = sorted(
                (m.start(), m.end(), gid)
                for gid, terms in GENRE_TERMS.items()
                for term in terms
                for m in re.finditer(r"\b" + re.escape(term) + r"\b", clause)
            )
            previous_end = 0
            for start, end, gid in matches:
                prefix = clause[previous_end:start]
                if re.search(r"\b(khong(?: thich| muon| xem| co)?|dung|tranh|loai|bo)\b", prefix) and not re.search(r"\bkhong chi\b", prefix):
                    negative = True
                elif re.search(r"\b(thich|muon|chon|xem|lay|khong chi|ma con)\b", prefix) or (previous_end == 0 and re.search(r"\bphim\b", prefix)):
                    negative = False
                (excluded if negative else wanted).append(gid)
                previous_end = end
            if wanted:
                combined = prefs.genre_ids + wanted if turn_wanted or re.search(r"\b(them|ca|hoac)\b", clause) else wanted
                prefs.genre_ids = list(dict.fromkeys(combined))[:5]
                turn_wanted = True
                prefs.excluded_genre_ids = [g for g in prefs.excluded_genre_ids if g not in wanted]
            if excluded:
                prefs.excluded_genre_ids = list(dict.fromkeys(prefs.excluded_genre_ids + excluded))[:5]
                prefs.genre_ids = [g for g in prefs.genre_ids if g not in excluded]
        if re.search(r"\b(?:bo|khong gioi han|khong can|bat ky)\s+(?:gioi han\s+)?(?:thoi luong|do dai)\b", text):
            prefs.min_runtime = prefs.max_runtime = None
        # Decimal hours and compound durations, e.g. 1,5 giờ or 1 giờ 30 phút.
        duration = r"(\d+(?:[.,]\d+)?)\s*(phut|tieng|gio)(?:\s*(?:ruoi|(?:(\d+)\s*phut)))?"
        for match in re.finditer(r"(duoi|toi da|khong qua|khong dai qua|ngan hon|tren|it nhat|toi thieu|hon|<|>)\s*" + duration, text):
            amount = float(match[2].replace(",", "."))
            minutes = round(amount * (1 if match[3] == "phut" else 60))
            if match[3] != "phut":
                minutes += int(match[4] or 0)
                if match[0].endswith("ruoi"):
                    minutes += 30
            if not 1 <= minutes <= 600:
                continue
            if match[1] in {"tren", "it nhat", "toi thieu", "hon", ">"}:
                prefs.min_runtime = minutes
                if "max" not in runtime_updated and prefs.max_runtime is not None and minutes > prefs.max_runtime:
                    prefs.max_runtime = None
                runtime_updated.add("min")
            else:
                prefs.max_runtime = minutes
                if "min" not in runtime_updated and prefs.min_runtime is not None and minutes < prefs.min_runtime:
                    prefs.min_runtime = None
                runtime_updated.add("max")
        if re.search(r"\b(bo gioi han nam|khong gioi han nam|nam nao cung duoc)\b", text):
            prefs.min_year = prefs.max_year = None
        year = r"((?:19|20)\d{2}|2100)"
        year_pattern = (
            r"(?:tu\s+(?:nam\s+)?)?" + year + r"\s*(?:den|toi|-)\s*(?:nam\s+)?" + year
            + r"|\b(sau|tu|truoc|den|toi)\s+(?:nam\s+)?" + year
            + r"|\bnam\s+" + year
        )
        for match in re.finditer(year_pattern, text):
            if match[1]:
                prefs.min_year, prefs.max_year = int(match[1]), int(match[2])
            elif match[3]:
                value = int(match[4])
                if match[3] in {"sau", "tu"}:
                    prefs.min_year = value + (match[3] == "sau")
                    if prefs.max_year is not None and prefs.max_year < prefs.min_year:
                        prefs.max_year = None
                else:
                    prefs.max_year = value - (match[3] == "truoc")
                    if prefs.min_year is not None and prefs.min_year > prefs.max_year:
                        prefs.min_year = None
            else:
                prefs.min_year = prefs.max_year = int(match[5])
        has_language, language = requested_language(text)
        if has_language:
            prefs.language = language
    return prefs


def describe_preferences(prefs: Preferences) -> str:
    bits = []
    if prefs.genre_ids:
        bits.append("thể loại " + " hoặc ".join(GENRES[g] for g in prefs.genre_ids if g in GENRES))
    if prefs.excluded_genre_ids:
        bits.append("tránh " + ", ".join(GENRES[g] for g in prefs.excluded_genre_ids if g in GENRES))
    if prefs.min_runtime:
        bits.append(f"từ {prefs.min_runtime} phút")
    if prefs.max_runtime:
        bits.append(f"tối đa {prefs.max_runtime} phút")
    if prefs.min_year:
        bits.append(f"từ năm {prefs.min_year}")
    if prefs.max_year:
        bits.append(f"đến năm {prefs.max_year}")
    if prefs.language:
        bits.append("ngôn ngữ gốc " + prefs.language)
    return "; ".join(bits)
