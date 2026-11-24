from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class Database:
    """Creates SQLite connections and owns the database schema."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    integration TEXT NOT NULL,
                    error_code TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('open', 'closed')),
                    occurrence_count INTEGER NOT NULL CHECK (occurrence_count > 0),
                    first_event_at TEXT NOT NULL,
                    last_event_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    closed_at TEXT,
                    resolution TEXT
                );

                CREATE UNIQUE INDEX IF NOT EXISTS ux_open_incident
                    ON incidents(integration, error_code)
                    WHERE status = 'open';

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    integration TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('success', 'failure')),
                    error_code TEXT,
                    message TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    incident_id INTEGER,
                    FOREIGN KEY (incident_id) REFERENCES incidents(id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS ix_events_failure_lookup
                    ON events(integration, error_code, status, occurred_at);
                CREATE INDEX IF NOT EXISTS ix_events_incident_id
                    ON events(incident_id);
                """
            )
