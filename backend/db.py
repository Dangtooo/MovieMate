from datetime import timezone

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import ROOT, get_settings


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    """SQLite stores naive UTC; expose aware UTC consistently to API callers."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return (
                value.replace(tzinfo=value.tzinfo or timezone.utc)
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )
        return value

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


def create_sqlite_engine(database_url: str):
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise ValueError(
            "Dự án dùng SQLite. Chạy python scripts/setup_env.py để cập nhật .env cũ."
        )
    if url.database and url.database != ":memory:":
        from pathlib import Path

        path = Path(url.database)
        if not path.is_absolute():
            path = ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        url = url.set(database=str(path.resolve()))
    db_engine = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
    )

    @event.listens_for(db_engine, "connect")
    def configure_sqlite(connection, record):
        # Explicit BEGIN fixes sqlite3 legacy savepoint/DDL transaction behavior.
        connection.isolation_level = None
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    @event.listens_for(db_engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN")

    return db_engine


engine = create_sqlite_engine(get_settings().database_url)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        yield db
