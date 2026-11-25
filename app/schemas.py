from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EventCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    event_id: str = Field(min_length=1, max_length=100)
    integration: str = Field(min_length=1, max_length=100)
    status: Literal["success", "failure"]
    message: str = Field(min_length=1, max_length=500)
    occurred_at: datetime
    error_code: str | None = Field(default=None, min_length=1, max_length=100)
    simulated_failures: int = Field(default=0, ge=0, le=20)

    @model_validator(mode="after")
    def validate_error_code(self) -> EventCreate:
        if self.status == "failure" and not self.error_code:
            raise ValueError("error_code é obrigatório para eventos de falha")
        if self.status == "success" and self.error_code:
            raise ValueError("error_code deve ser omitido em eventos de sucesso")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at precisa conter fuso horário")
        return self


class IncidentResponse(BaseModel):
    id: int
    integration: str
    error_code: str
    title: str
    status: Literal["open", "closed"]
    occurrence_count: int
    first_event_at: datetime
    last_event_at: datetime
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    resolution: str | None


class EventProcessingResponse(BaseModel):
    duplicate: bool
    action: Literal["event_recorded", "incident_opened", "incident_updated", "duplicate_ignored"]
    event_id: str
    incident: IncidentResponse | None


class CloseIncidentRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    resolution: str = Field(min_length=3, max_length=1000)


class HealthResponse(BaseModel):
    status: Literal["ok"]


class IncidentAnalysisResponse(BaseModel):
    incident_id: int
    summary: str
    suggested_investigation: list[str]
    disclaimer: str


class EventResponse(BaseModel):
    id: int
    event_id: str
    integration: str
    status: Literal["success", "failure"]
    error_code: str | None
    message: str
    occurred_at: datetime
    received_at: datetime


class DeliveryResponse(BaseModel):
    id: int
    event_id: str | None = None
    status: Literal["pending", "running", "succeeded", "exhausted"]
    cycle: int
    attempt_count: int
    next_attempt_at: datetime | None
    last_error: str | None


class AttemptResponse(BaseModel):
    id: int
    delivery_id: int
    cycle: int
    attempt_number: int
    started_at: datetime
    finished_at: datetime
    result: Literal["failed", "succeeded"]
    failure_reason: str | None
