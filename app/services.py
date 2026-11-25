from __future__ import annotations

import os
from datetime import timedelta
from uuid import uuid4

from app.database import Database
from app.models import EventData, ProcessingResult, utc_now


class IncidentNotFoundError(LookupError):
    pass


class ReprocessConflictError(ValueError):
    pass


class IncidentService:
    def __init__(
        self, database: Database, *, failure_threshold: int = 3,
        repetition_window_minutes: int = 30,
    ) -> None:
        self.database = database
        self.failure_threshold = failure_threshold
        self.repetition_window = timedelta(minutes=repetition_window_minutes)

    def process_event(self, event: EventData, simulated_failures: int = 0) -> ProcessingResult:
        with self.database.connection() as connection:
            # Serialize threshold checks for each integration/error pair.
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                (event.integration, event.error_code or ""),
            )
            stored = connection.execute(
                """INSERT INTO events (event_id, integration, status, error_code, message,
                   occurred_at, received_at, simulated_failures)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (event_id) DO NOTHING RETURNING id""",
                (event.event_id, event.integration, event.status, event.error_code,
                 event.message, event.occurred_at, utc_now(), simulated_failures),
            ).fetchone()
            if stored is None:
                duplicate = connection.execute(
                    "SELECT incident_id FROM events WHERE event_id = %s", (event.event_id,)
                ).fetchone()
                return ProcessingResult(
                    True, "duplicate_ignored", event.event_id,
                    self._get_incident(connection, duplicate["incident_id"]),
                )
            event_pk = stored["id"]
            connection.execute(
                "INSERT INTO deliveries (event_id, status, next_attempt_at) VALUES (%s, 'pending', %s)",
                (event_pk, utc_now()),
            )
            if event.status == "success":
                return ProcessingResult(False, "event_recorded", event.event_id, None)

            open_incident = connection.execute(
                """SELECT * FROM incidents WHERE integration = %s AND error_code = %s
                   AND status = 'open' FOR UPDATE""",
                (event.integration, event.error_code),
            ).fetchone()
            if open_incident:
                connection.execute(
                    """UPDATE incidents SET occurrence_count = occurrence_count + 1,
                       first_event_at = LEAST(first_event_at, %s),
                       last_event_at = GREATEST(last_event_at, %s), updated_at = %s WHERE id = %s""",
                    (event.occurred_at, event.occurred_at, utc_now(), open_incident["id"]),
                )
                connection.execute(
                    "UPDATE events SET incident_id = %s WHERE id = %s",
                    (open_incident["id"], event_pk),
                )
                return ProcessingResult(
                    False, "incident_updated", event.event_id,
                    self._get_incident(connection, open_incident["id"]),
                )

            matches = connection.execute(
                """SELECT id, occurred_at FROM events WHERE integration = %s AND error_code = %s
                   AND status = 'failure' AND incident_id IS NULL
                   AND occurred_at BETWEEN %s AND %s ORDER BY occurred_at, id""",
                (event.integration, event.error_code,
                 event.occurred_at - self.repetition_window, event.occurred_at),
            ).fetchall()
            if len(matches) < self.failure_threshold:
                return ProcessingResult(False, "event_recorded", event.event_id, None)
            incident = connection.execute(
                """INSERT INTO incidents (integration, error_code, title, status,
                   occurrence_count, first_event_at, last_event_at, created_at, updated_at)
                   VALUES (%s, %s, %s, 'open', %s, %s, %s, %s, %s) RETURNING id""",
                (event.integration, event.error_code,
                 f"Falhas repetidas em {event.integration}: {event.error_code}",
                 len(matches), matches[0]["occurred_at"], matches[-1]["occurred_at"],
                 utc_now(), utc_now()),
            ).fetchone()
            connection.execute(
                "UPDATE events SET incident_id = %s WHERE id = ANY(%s)",
                (incident["id"], [row["id"] for row in matches]),
            )
            return ProcessingResult(
                False, "incident_opened", event.event_id,
                self._get_incident(connection, incident["id"]),
            )

    def list_incidents(
        self, status: str | None = None, integration: str | None = None,
        error_code: str | None = None, limit: int = 50, offset: int = 0,
    ) -> list[dict[str, object]]:
        with self.database.connection() as connection:
            return connection.execute(
                """SELECT * FROM incidents WHERE (%s::text IS NULL OR status = %s)
                   AND (%s::text IS NULL OR integration = %s)
                   AND (%s::text IS NULL OR error_code = %s)
                   ORDER BY updated_at DESC, id DESC LIMIT %s OFFSET %s""",
                (status, status, integration, integration, error_code, error_code, limit, offset),
            ).fetchall()

    def counts(self) -> dict[str, int]:
        with self.database.connection() as connection:
            row = connection.execute(
                """SELECT count(*) FILTER (WHERE status = 'open') AS open,
                   count(*) FILTER (WHERE status = 'closed') AS closed FROM incidents"""
            ).fetchone()
            return {"open": row["open"], "closed": row["closed"]}

    def get_incident(self, incident_id: int) -> dict[str, object]:
        with self.database.connection() as connection:
            incident = self._get_incident(connection, incident_id)
            if incident is None:
                raise IncidentNotFoundError(f"Incidente {incident_id} não encontrado")
            return incident

    def get_timeline(self, incident_id: int, limit: int = 100, offset: int = 0) -> list[dict]:
        with self.database.connection() as connection:
            if self._get_incident(connection, incident_id) is None:
                raise IncidentNotFoundError(f"Incidente {incident_id} não encontrado")
            return connection.execute(
                """SELECT id, event_id, integration, status, error_code, message,
                   occurred_at, received_at FROM events WHERE incident_id = %s
                   ORDER BY occurred_at, id LIMIT %s OFFSET %s""",
                (incident_id, limit, offset),
            ).fetchall()

    def list_deliveries(self, incident_id: int, limit: int = 100, offset: int = 0) -> list[dict]:
        with self.database.connection() as connection:
            if self._get_incident(connection, incident_id) is None:
                raise IncidentNotFoundError(f"Incidente {incident_id} não encontrado")
            return connection.execute(
                """SELECT d.id, e.event_id, d.status, d.cycle, d.attempt_count,
                   d.next_attempt_at, d.last_error FROM deliveries d JOIN events e ON e.id = d.event_id
                   WHERE e.incident_id = %s ORDER BY d.id LIMIT %s OFFSET %s""",
                (incident_id, limit, offset),
            ).fetchall()

    def list_attempts(self, delivery_id: int, limit: int = 100, offset: int = 0) -> list[dict]:
        with self.database.connection() as connection:
            if not connection.execute("SELECT 1 FROM deliveries WHERE id = %s", (delivery_id,)).fetchone():
                raise IncidentNotFoundError(f"Entrega {delivery_id} não encontrada")
            return connection.execute(
                """SELECT id, delivery_id, cycle, attempt_number, started_at, finished_at,
                   result, failure_reason FROM delivery_attempts WHERE delivery_id = %s
                   ORDER BY id LIMIT %s OFFSET %s""",
                (delivery_id, limit, offset),
            ).fetchall()

    def reprocess(self, delivery_id: int) -> dict:
        with self.database.connection() as connection:
            delivery = connection.execute(
                "SELECT * FROM deliveries WHERE id = %s FOR UPDATE", (delivery_id,)
            ).fetchone()
            if delivery is None:
                raise IncidentNotFoundError(f"Entrega {delivery_id} não encontrada")
            if delivery["status"] not in ("exhausted", "pending"):
                raise ReprocessConflictError("Somente entregas pendentes ou esgotadas podem ser reprocessadas")
            # Demo recovery: manual retry clears the simulated outage.
            connection.execute("UPDATE events SET simulated_failures = 0 WHERE id = %s", (delivery["event_id"],))
            cycle = delivery["cycle"] + 1
            return connection.execute(
                """UPDATE deliveries SET status = 'pending', cycle = %s, attempt_count = 0,
                   next_attempt_at = %s, last_error = NULL, lease_until = NULL, claim_token = NULL
                   WHERE id = %s RETURNING id, status, cycle, attempt_count, next_attempt_at, last_error""",
                (cycle, utc_now(), delivery_id),
            ).fetchone()

    def close_incident(self, incident_id: int, resolution: str) -> dict[str, object]:
        resolution = resolution.strip()
        if len(resolution) < 3:
            raise ValueError("A resolução precisa ter pelo menos 3 caracteres")
        with self.database.connection() as connection:
            incident = connection.execute(
                "SELECT * FROM incidents WHERE id = %s FOR UPDATE", (incident_id,)
            ).fetchone()
            if incident is None:
                raise IncidentNotFoundError(f"Incidente {incident_id} não encontrado")
            if incident["status"] == "closed":
                return incident
            now = utc_now()
            return connection.execute(
                """UPDATE incidents SET status = 'closed', resolution = %s, closed_at = %s,
                   updated_at = %s WHERE id = %s RETURNING *""",
                (resolution, now, now, incident_id),
            ).fetchone()

    @staticmethod
    def _get_incident(connection, incident_id: int | None) -> dict[str, object] | None:
        if incident_id is None:
            return None
        return connection.execute(
            "SELECT * FROM incidents WHERE id = %s", (incident_id,)
        ).fetchone()


class DeliveryService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.max_attempts = int(os.getenv("DELIVERY_MAX_ATTEMPTS", "3"))
        self.base_delay = int(os.getenv("DELIVERY_BASE_DELAY_SECONDS", "5"))
        if self.max_attempts < 1 or self.base_delay < 1:
            raise ValueError("DELIVERY_MAX_ATTEMPTS e DELIVERY_BASE_DELAY_SECONDS devem ser positivos")

    def run_once(self) -> bool:
        delivery = self.claim_next()
        return self.complete_claim(delivery) if delivery else False

    def claim_next(self) -> dict | None:
        now = utc_now()
        with self.database.connection() as connection:
            delivery = connection.execute(
                """SELECT d.*, e.simulated_failures FROM deliveries d JOIN events e ON e.id = d.event_id
                   WHERE (d.status = 'pending' AND d.next_attempt_at <= %s)
                      OR (d.status = 'running' AND d.lease_until <= %s)
                   ORDER BY d.next_attempt_at, d.id FOR UPDATE OF d SKIP LOCKED LIMIT 1""",
                (now, now),
            ).fetchone()
            if delivery is None:
                return None
            token = uuid4().hex
            connection.execute(
                """UPDATE deliveries SET status = 'running', lease_until = %s,
                   claim_token = %s WHERE id = %s""",
                (now + timedelta(minutes=1), token, delivery["id"]),
            )
            return {**delivery, "claim_token": token, "started_at": now}

    def complete_claim(self, delivery: dict) -> bool:
        with self.database.connection() as connection:
            current = connection.execute(
                "SELECT status, claim_token FROM deliveries WHERE id = %s FOR UPDATE",
                (delivery["id"],),
            ).fetchone()
            if current["status"] != "running" or current["claim_token"] != delivery["claim_token"]:
                return False
            number = delivery["attempt_count"] + 1
            # This simulated destination has no external side effects.
            failed = number <= delivery["simulated_failures"]
            reason = "Destino fictício indisponível" if failed else None
            connection.execute(
                """INSERT INTO delivery_attempts (delivery_id, cycle, attempt_number,
                   started_at, finished_at, result, failure_reason)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (delivery["id"], delivery["cycle"], number, delivery["started_at"], utc_now(),
                 "failed" if failed else "succeeded", reason),
            )
            state = "exhausted" if failed and number >= self.max_attempts else (
                "pending" if failed else "succeeded"
            )
            next_attempt = (
                utc_now() + timedelta(seconds=self.base_delay * (2 ** (number - 1)))
                if failed and state == "pending" else None
            )
            connection.execute(
                """UPDATE deliveries SET status = %s, attempt_count = %s, next_attempt_at = %s,
                   last_error = %s, lease_until = NULL, claim_token = NULL WHERE id = %s""",
                (state, number, next_attempt, reason, delivery["id"]),
            )
            return True
