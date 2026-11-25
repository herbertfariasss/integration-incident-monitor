from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.database import Database
from app.models import EventData, utc_now
from app.services import DeliveryService, IncidentService


def failure(number: int, event_id: str | None = None) -> EventData:
    return EventData(
        event_id=event_id or f"delivery-{number}", integration="sandbox-api",
        status="failure", error_code="DEMO_ERROR", message="Falha fictícia",
        occurred_at=datetime(2026, 11, 25, 12, 0, tzinfo=UTC) + timedelta(minutes=number),
    )


def test_concurrent_duplicate_is_recorded_once(service: IncidentService, database: Database) -> None:
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(service.process_event, [failure(1, "same-id")] * 8))
    assert sum(not result.duplicate for result in results) == 1
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) AS n FROM events").fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) AS n FROM deliveries").fetchone()["n"] == 1


def test_persistence_and_repeatable_migrations(database: Database) -> None:
    IncidentService(database).process_event(failure(1))
    database.initialize()
    with Database(database.url).connection() as connection:
        assert connection.execute("SELECT event_id FROM events").fetchone()["event_id"] == "delivery-1"
        assert connection.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"] == 2


def test_failed_attempt_limit_and_manual_recovery(database: Database, monkeypatch) -> None:
    monkeypatch.setenv("DELIVERY_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("DELIVERY_BASE_DELAY_SECONDS", "1")
    incidents = IncidentService(database)
    for number in range(1, 4):
        incidents.process_event(failure(number), simulated_failures=3)
    incident_id = incidents.list_incidents()[0]["id"]
    delivery_id = incidents.list_deliveries(incident_id)[0]["id"]
    with database.connection() as connection:
        connection.execute(
            "UPDATE deliveries SET next_attempt_at = %s WHERE id <> %s",
            (utc_now() + timedelta(days=1), delivery_id),
        )
    worker = DeliveryService(database)
    assert worker.run_once() is True
    with database.connection() as connection:
        connection.execute(
            "UPDATE deliveries SET next_attempt_at = %s WHERE id = %s", (utc_now(), delivery_id)
        )
    assert worker.run_once() is True
    assert incidents.list_deliveries(incident_id)[0]["status"] == "exhausted"
    assert [item["result"] for item in incidents.list_attempts(delivery_id)] == ["failed", "failed"]
    incidents.reprocess(delivery_id)
    assert worker.run_once() is True
    assert incidents.list_deliveries(incident_id)[0]["status"] == "succeeded"
    attempts = incidents.list_attempts(delivery_id)
    assert [item["result"] for item in attempts] == ["failed", "failed", "succeeded"]
    assert attempts[-1]["cycle"] == 2


def test_expired_running_claim_is_recovered(database: Database) -> None:
    incidents = IncidentService(database)
    for number in range(1, 4):
        incidents.process_event(failure(number))
    incident_id = incidents.list_incidents()[0]["id"]
    delivery_id = incidents.list_deliveries(incident_id)[0]["id"]
    worker = DeliveryService(database)
    claim = worker.claim_next()
    assert claim is not None
    assert incidents.list_deliveries(incident_id)[0]["status"] == "running"
    with database.connection() as connection:
        connection.execute(
            "UPDATE deliveries SET lease_until = %s WHERE id = %s",
            (utc_now() - timedelta(minutes=1), delivery_id),
        )
    assert worker.run_once() is True
    assert worker.complete_claim(claim) is False
    assert incidents.list_deliveries(incident_id)[0]["status"] == "succeeded"
    assert len(incidents.list_attempts(delivery_id)) == 1


def test_new_endpoints_and_filters(client: TestClient) -> None:
    for number in range(1, 4):
        response = client.post("/api/v1/events", json={
            "event_id": f"api-{number}", "integration": "sandbox-api", "status": "failure",
            "error_code": "DEMO_ERROR", "message": "Falha fictícia",
            "occurred_at": f"2026-11-25T12:0{number}:00Z", "simulated_failures": 3,
        })
        assert response.status_code == 202
    incident_id = response.json()["incident"]["id"]
    assert client.get("/api/v1/incidents/counts").json() == {"open": 1, "closed": 0}
    assert len(client.get("/api/v1/incidents", params={"integration": "sandbox-api"}).json()) == 1
    assert client.get("/api/v1/incidents", params={"error_code": "OTHER"}).json() == []
    assert client.get("/api/v1/incidents", params={"offset": 1}).json() == []
    events = client.get(f"/api/v1/incidents/{incident_id}/events").json()
    assert len(events) == 3
    assert [item["event_id"] for item in events] == ["api-1", "api-2", "api-3"]
    deliveries = client.get(f"/api/v1/incidents/{incident_id}/deliveries").json()
    assert len(deliveries) == 3
    delivery_id = deliveries[0]["id"]
    assert client.get(f"/api/v1/deliveries/{delivery_id}/attempts").json() == []
    assert client.post(f"/api/v1/deliveries/{delivery_id}/reprocess").status_code == 200
    assert client.get("/api/v1/incidents", params={"limit": 101}).status_code == 422
