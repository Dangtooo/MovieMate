"""One-time copy from the retained PostgreSQL config; source is never changed."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from dotenv import dotenv_values
    from sqlalchemy import MetaData, Table, create_engine, func, select
    from backend.db import Base, engine
    from backend.models import Movie, User, Review, Watchlist

    backup = ROOT / ".local" / ".env.before-sqlite"
    marker = ROOT / ".local" / "sqlite-migration.json"
    if marker.exists():
        print("Legacy data was already copied to SQLite. No data changed.")
        return
    if not backup.exists():
        raise SystemExit(
            "No legacy configuration found. New installations do not need migration."
        )
    source_url = dotenv_values(backup).get("DATABASE_URL", "")
    if not source_url.startswith("postgresql"):
        raise SystemExit("The legacy source must be PostgreSQL.")
    source = create_engine(source_url)
    Base.metadata.create_all(engine)
    counts = {}
    # One atomic destination transaction. Refuse to merge colliding user IDs.
    with source.connect() as old, engine.begin() as new:
        tables = [
            User.__table__,
            Movie.__table__,
            Review.__table__,
            Watchlist.__table__,
        ]
        if any(new.scalar(select(func.count()).select_from(table)) for table in tables):
            raise SystemExit(
                "SQLite already contains data. Migration cancelled; no rows copied."
            )
        for table in tables:
            legacy = Table(table.name, MetaData(), autoload_with=source)
            rows = [dict(row) for row in old.execute(select(legacy)).mappings()]
            if rows:
                new.execute(table.insert(), rows)
            counts[table.name] = len(rows)
    source.dispose()
    marker.write_text(json.dumps(counts, indent=2), encoding="utf-8")
    print("Copied to SQLite (legacy database preserved): " + json.dumps(counts))


if __name__ == "__main__":
    main()
