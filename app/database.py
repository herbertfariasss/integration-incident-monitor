from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


class Database:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.environ.get(
            "DATABASE_URL", "postgresql://incident:incident@localhost:5432/incidents"
        )

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            yield connection

    def initialize(self) -> None:
        migrations = sorted((Path(__file__).parent.parent / "migrations").glob("*.sql"))
        with self.connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY)"
            )
            for migration in migrations:
                if connection.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = %s", (migration.name,)
                ).fetchone():
                    continue
                connection.execute(migration.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)", (migration.name,)
                )
