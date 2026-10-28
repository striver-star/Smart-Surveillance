"""Database connection and the small migration runner used until Phase 1 adds a full tool."""
import os
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).parent / "migrations"


def database_url() -> str:
    return os.environ["HSS_DATABASE_URL"]


def connect(**kwargs) -> psycopg.Connection:
    return psycopg.connect(database_url(), **kwargs)


def migrate() -> list[str]:
    """Apply each migrations/*.sql file once, in name order."""
    applied = []
    with connect() as conn:
        conn.execute("SELECT pg_advisory_lock(7313)")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                     "(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name in done:
                continue
            conn.execute(path.read_text())
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            applied.append(path.name)
        conn.commit()
        conn.execute("SELECT pg_advisory_unlock(7313)")
    return applied
