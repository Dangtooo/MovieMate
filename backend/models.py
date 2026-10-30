from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, UTCDateTime


class Movie(Base):
    __tablename__ = "movies"
    # The ONLY movie identifier: there is deliberately no movies.id column.
    tmdb_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(String(300), index=True)
    original_title: Mapped[str] = mapped_column(String(300), default="")
    overview: Mapped[str] = mapped_column(Text, default="")
    poster_path: Mapped[str | None] = mapped_column(String(300))
    backdrop_path: Mapped[str | None] = mapped_column(String(300))
    release_date: Mapped[date | None]
    runtime: Mapped[int | None]
    genre_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    original_language: Mapped[str] = mapped_column(String(10), default="")
    tmdb_rating: Mapped[float] = mapped_column(default=0.0)
    popularity: Mapped[float] = mapped_column(default=0.0)
    trailer_key: Mapped[str | None] = mapped_column(String(30))
    cast_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now()
    )
    details_fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now()
    )


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("user_id", "movie_tmdb_id"),
        CheckConstraint("rating BETWEEN 1 AND 10", name="review_rating_range"),
        CheckConstraint(
            "length(content) BETWEEN 10 AND 3000", name="review_content_length"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    movie_tmdb_id: Mapped[int] = mapped_column(
        ForeignKey("movies.tmdb_id", ondelete="CASCADE"), index=True
    )
    rating: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    contains_spoiler: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now()
    )


class Watchlist(Base):
    __tablename__ = "watchlists"
    __table_args__ = (
        CheckConstraint(
            "status IN ('want_to_watch', 'watched')", name="watchlist_status"
        ),
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    movie_tmdb_id: Mapped[int] = mapped_column(
        ForeignKey("movies.tmdb_id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(20), default="want_to_watch")
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now()
    )
