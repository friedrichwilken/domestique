"""Postgres connection and plain-SQL migration runner."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import psycopg

# Rows come straight from the database as untyped tuples.
type Conn = psycopg.Connection[tuple[Any, ...]]

DEFAULT_DSN = "postgresql://domestique:domestique@localhost:5432/domestique"
MIGRATIONS_DIR = Path(
    os.environ.get("DOMESTIQUE_MIGRATIONS", Path(__file__).parents[2] / "migrations")
)


def connect(dsn: str | None = None) -> Conn:
    return psycopg.connect(dsn or os.environ.get("DOMESTIQUE_DSN", DEFAULT_DSN))


def migrate(conn: Conn, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply unapplied ``NNNN_*.sql`` files in order; returns the names applied."""
    with conn.transaction():
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
    done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
    applied: list[str] = []
    for path in sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text())
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
        applied.append(path.name)
    return applied
