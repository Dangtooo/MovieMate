from sqlalchemy import func, select

from .models import Movie


def has_any_genre(genre_ids: list[int]):
    """Match exact integer elements in a SQLite JSON array, not substrings."""
    genres = func.json_each(Movie.genre_ids).table_valued("key", "value")
    return select(1).select_from(genres).where(genres.c.value.in_(genre_ids)).exists()
