from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

BASE_TIME = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def event_payload(number: int) -> dict[str, str]:
    return {
        "event_id": f"route-event-{number}",
        "integration": "erp-orders",
        "status": "failure",
        "error_code": "HTTP_503",
        "message": "ERP temporariamente indisponível.",
        "occurred_at": (BASE_TIME + timedelta(minutes=number)).isoformat(),
    }


def test_health_route(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_event_and_incident_routes(client: TestClient) -> None:
    responses = [
        client.post("/api/v1/events", json=event_payload(number)) for number in range(1, 4)
    ]

    assert all(response.status_code == 202 for response in responses)
    assert responses[-1].json()["action"] == "incident_opened"

    list_response = client.get("/api/v1/incidents", params={"status": "open"})
    assert list_response.status_code == 200
    incidents = list_response.json()
    assert len(incidents) == 1
    assert incidents[0]["occurrence_count"] == 3

    incident_id = incidents[0]["id"]
    close_response = client.patch(
        f"/api/v1/incidents/{incident_id}/close",
        json={"resolution": "Serviço do ERP normalizado."},
    )
    assert close_response.status_code == 200
    assert close_response.json()["status"] == "closed"


def test_duplicate_event_route(client: TestClient) -> None:
    payload = event_payload(1)
    client.post("/api/v1/events", json=payload)

    response = client.post("/api/v1/events", json=payload)

    assert response.status_code == 202
    assert response.json()["duplicate"] is True
    assert response.json()["action"] == "duplicate_ignored"


def test_failure_requires_error_code(client: TestClient) -> None:
    payload = event_payload(1)
    payload.pop("error_code")

    response = client.post("/api/v1/events", json=payload)

    assert response.status_code == 422


def test_unknown_incident_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/incidents/999")

    assert response.status_code == 404


def test_ai_analysis_route_uses_configured_assistant(ai_client: TestClient) -> None:
    for number in range(1, 4):
        ai_client.post("/api/v1/events", json=event_payload(number))
    incident_id = ai_client.get("/api/v1/incidents").json()[0]["id"]

    response = ai_client.post(f"/api/v1/incidents/{incident_id}/ai-analysis")

    assert response.status_code == 200
    body = response.json()
    assert body["incident_id"] == incident_id
    assert "3 falhas" in body["summary"]
    assert len(body["suggested_investigation"]) == 2
    assert "Confira" in body["disclaimer"]


def test_ai_analysis_route_is_optional(client: TestClient) -> None:
    response = client.post("/api/v1/incidents/1/ai-analysis")

    assert response.status_code == 503
