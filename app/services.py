from __future__ import annotations

import sqlite3
from datetime import timedelta

from app.database import Database
from app.models import EventData, ProcessingResult, utc_now


class IncidentNotFoundError(LookupError):
    pass


class IncidentService:
    """Applies incident rules independently from the HTTP layer."""

    def __init__(
        self,
        database: Database,
        *,
        failure_threshold: int = 3,
        repetition_window_minutes: int = 30,
    ) -> None:
        if failure_threshold < 2:
            raise ValueError("failure_threshold precisa ser pelo menos 2")
        self.database = database
        self.failure_threshold = failure_threshold
        self.repetition_window = timedelta(minutes=repetition_window_minutes)

    def process_event(self, event: EventData) -> ProcessingResult:
        occurred_at = event.occurred_at.isoformat()
        received_at = utc_now().isoformat()

        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute(
                "SELECT event_id, incident_id FROM events WHERE event_id = ?",
                (event.event_id,),
            ).fetchone()
            if duplicate:
                incident = self._get_incident(connection, duplicate["incident_id"])
                return ProcessingResult(
                    duplicate=True,
                    action="duplicate_ignored",
                    event_id=event.event_id,
                    incident=incident,
                )

            cursor = connection.execute(
                """
                INSERT INTO events (
                    event_id, integration, status, error_code, message,
                    occurred_at, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.integration,
                    event.status,
                    event.error_code,
                    event.message,
                    occurred_at,
                    received_at,
                ),
            )
            stored_event_id = cursor.lastrowid

            if event.status == "success":
                return ProcessingResult(False, "event_recorded", event.event_id, None)

            open_incident = connection.execute(
                """
                SELECT * FROM incidents
                WHERE integration = ? AND error_code = ? AND status = 'open'
                """,
                (event.integration, event.error_code),
            ).fetchone()

            if open_incident:
                now = utc_now().isoformat()
                connection.execute(
                    """
                    UPDATE incidents
                    SET occurrence_count = occurrence_count + 1,
                        last_event_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (occurred_at, now, open_incident["id"]),
                )
                connection.execute(
                    "UPDATE events SET incident_id = ? WHERE id = ?",
                    (open_incident["id"], stored_event_id),
                )
                incident = self._get_incident(connection, open_incident["id"])
                return ProcessingResult(False, "incident_updated", event.event_id, incident)

            cutoff = (event.occurred_at - self.repetition_window).isoformat()
            matching_failures = connection.execute(
                """
                SELECT id, occurred_at FROM events
                WHERE integration = ?
                  AND error_code = ?
                  AND status = 'failure'
                  AND incident_id IS NULL
                  AND occurred_at BETWEEN ? AND ?
                ORDER BY occurred_at ASC, id ASC
                """,
                (event.integration, event.error_code, cutoff, occurred_at),
            ).fetchall()

            if len(matching_failures) < self.failure_threshold:
                return ProcessingResult(False, "event_recorded", event.event_id, None)

            now = utc_now().isoformat()
            incident_cursor = connection.execute(
                """
                INSERT INTO incidents (
                    integration, error_code, title, status, occurrence_count,
                    first_event_at, last_event_at, created_at, updated_at
                ) VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?)
                """,
                (
                    event.integration,
                    event.error_code,
                    f"Falhas repetidas em {event.integration}: {event.error_code}",
                    len(matching_failures),
                    matching_failures[0]["occurred_at"],
                    matching_failures[-1]["occurred_at"],
                    now,
                    now,
                ),
            )
            incident_id = incident_cursor.lastrowid
            placeholders = ",".join("?" for _ in matching_failures)
            event_ids = [row["id"] for row in matching_failures]
            connection.execute(
                f"UPDATE events SET incident_id = ? WHERE id IN ({placeholders})",  # noqa: S608
                (incident_id, *event_ids),
            )
            incident = self._get_incident(connection, incident_id)
            return ProcessingResult(False, "incident_opened", event.event_id, incident)

    def list_incidents(self, status: str | None = None) -> list[dict[str, object]]:
        query = "SELECT * FROM incidents"
        parameters: tuple[str, ...] = ()
        if status:
            query += " WHERE status = ?"
            parameters = (status,)
        query += " ORDER BY updated_at DESC, id DESC"

        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
            return [dict(row) for row in rows]

    def get_incident(self, incident_id: int) -> dict[str, object]:
        with self.database.connection() as connection:
            incident = self._get_incident(connection, incident_id)
            if incident is None:
                raise IncidentNotFoundError(f"Incidente {incident_id} não encontrado")
            return incident

    def close_incident(self, incident_id: int, resolution: str) -> dict[str, object]:
        resolution = resolution.strip()
        if len(resolution) < 3:
            raise ValueError("A resolução precisa ter pelo menos 3 caracteres")

        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            incident = connection.execute(
                "SELECT * FROM incidents WHERE id = ?",
                (incident_id,),
            ).fetchone()
            if incident is None:
                raise IncidentNotFoundError(f"Incidente {incident_id} não encontrado")
            if incident["status"] == "closed":
                return dict(incident)

            now = utc_now().isoformat()
            connection.execute(
                """
                UPDATE incidents
                SET status = 'closed', resolution = ?, closed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (resolution, now, now, incident_id),
            )
            closed = self._get_incident(connection, incident_id)
            assert closed is not None
            return closed

    @staticmethod
    def _get_incident(
        connection: sqlite3.Connection,
        incident_id: int | None,
    ) -> dict[str, object] | None:
        if incident_id is None:
            return None
        row = connection.execute(
            "SELECT * FROM incidents WHERE id = ?",
            (incident_id,),
        ).fetchone()
        return dict(row) if row else None
