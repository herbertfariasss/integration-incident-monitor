from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("occurred_at precisa conter fuso horário")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class EventData:
    event_id: str
    integration: str
    status: Literal["success", "failure"]
    message: str
    occurred_at: datetime
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.status == "failure" and not self.error_code:
            raise ValueError("error_code é obrigatório para eventos de falha")
        if self.status == "success" and self.error_code:
            raise ValueError("error_code deve ser omitido em eventos de sucesso")
        object.__setattr__(self, "occurred_at", normalize_datetime(self.occurred_at))


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    duplicate: bool
    action: Literal["event_recorded", "incident_opened", "incident_updated", "duplicate_ignored"]
    event_id: str
    incident: dict[str, object] | None
