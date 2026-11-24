from datetime import UTC, datetime, timedelta

from app.models import EventData
from app.services import IncidentService

BASE_TIME = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def failure(number: int, *, minutes: int = 0) -> EventData:
    return EventData(
        event_id=f"evt-{number}",
        integration="crm-webhook",
        status="failure",
        error_code="TIMEOUT",
        message="O CRM não respondeu dentro do limite.",
        occurred_at=BASE_TIME + timedelta(minutes=minutes),
    )


def test_duplicate_event_does_not_increment_failure_count(service: IncidentService) -> None:
    first = service.process_event(failure(1))
    duplicate = service.process_event(failure(1))

    assert first.action == "event_recorded"
    assert duplicate.duplicate is True
    assert duplicate.action == "duplicate_ignored"
    assert service.list_incidents() == []


def test_third_repeated_failure_opens_incident(service: IncidentService) -> None:
    service.process_event(failure(1, minutes=0))
    service.process_event(failure(2, minutes=5))
    result = service.process_event(failure(3, minutes=10))

    assert result.action == "incident_opened"
    assert result.incident is not None
    assert result.incident["status"] == "open"
    assert result.incident["occurrence_count"] == 3


def test_new_failure_updates_open_incident(service: IncidentService) -> None:
    for number in range(1, 4):
        service.process_event(failure(number, minutes=number))

    result = service.process_event(failure(4, minutes=8))

    assert result.action == "incident_updated"
    assert result.incident is not None
    assert result.incident["occurrence_count"] == 4


def test_failures_outside_window_do_not_open_incident(service: IncidentService) -> None:
    service.process_event(failure(1, minutes=0))
    service.process_event(failure(2, minutes=31))
    result = service.process_event(failure(3, minutes=62))

    assert result.action == "event_recorded"
    assert service.list_incidents() == []


def test_incident_can_be_closed_with_resolution(service: IncidentService) -> None:
    for number in range(1, 4):
        service.process_event(failure(number, minutes=number))
    incident_id = service.list_incidents()[0]["id"]

    closed = service.close_incident(int(incident_id), "Timeout ajustado para 15 segundos.")

    assert closed["status"] == "closed"
    assert closed["closed_at"] is not None
    assert closed["resolution"] == "Timeout ajustado para 15 segundos."
