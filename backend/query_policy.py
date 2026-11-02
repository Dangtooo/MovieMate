"""Deterministic output order shared by retrieval and model synthesis."""

from datetime import date, datetime, timedelta, timezone


def today():
    """The app's release cutoff uses the user's UTC+7 day, not the host timezone."""
    return datetime.now(timezone(timedelta(hours=7))).date()


def release_date(value):
    try:
        return date.fromisoformat(value) if value else date.min
    except (TypeError, ValueError):
        return date.min


def sort_rows(rows, mode="newest", minimum_votes=0, release_scope=None, cutoff=None):
    cutoff = cutoff or today()
    unique = {}
    for row in rows:
        if not row.get("id") or row.get("adult"):
            continue
        released = release_date(row.get("release_date"))
        if release_scope and (released == date.min or
                              (release_scope == "released" and released > cutoff) or
                              (release_scope == "upcoming" and released <= cutoff)):
            continue
        if mode == "rating" and (row.get("vote_count") or 0) < minimum_votes:
            continue
        unique.setdefault(row["id"], row)
    if mode == "rating":
        key = lambda r: (r.get("vote_average") or 0, release_date(r.get("release_date")))
    else:
        key = lambda r: release_date(r.get("release_date"))
    return sorted(unique.values(), key=key, reverse=True)


def sort_cards(cards, mode="newest"):
    def released(card):
        return release_date(card.get("release_date") or (card["release_year"] + "-01-01" if card.get("release_year") else None))
    key = (lambda m: (m.get("rating") or 0, released(m))) if mode == "rating" else released
    return sorted(cards, key=key, reverse=True)
