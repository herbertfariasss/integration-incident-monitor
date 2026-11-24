from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, status

from app.ai import IncidentAssistant, OpenAICompatibleIncidentAssistant
from app.database import Database
from app.models import EventData
from app.schemas import (
    CloseIncidentRequest,
    EventCreate,
    EventProcessingResponse,
    HealthResponse,
    IncidentAnalysisResponse,
    IncidentResponse,
)
from app.services import IncidentNotFoundError, IncidentService


def create_app(
    database_path: str | Path | None = None,
    *,
    incident_assistant: IncidentAssistant | None = None,
) -> FastAPI:
    resolved_path = database_path or os.getenv("INCIDENT_DB_PATH", "incidents.db")
    database = Database(resolved_path)
    service = IncidentService(database)
    if incident_assistant is None:
        ai_api_url = os.getenv("AI_API_URL")
        ai_api_key = os.getenv("AI_API_KEY")
        ai_model = os.getenv("AI_MODEL")
        if ai_api_url and ai_api_key and ai_model:
            incident_assistant = OpenAICompatibleIncidentAssistant(
                api_url=ai_api_url,
                api_key=ai_api_key,
                model=ai_model,
            )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.initialize()
        yield

    app = FastAPI(
        title="Integration Incident Monitor",
        version="0.1.0",
        description=(
            "Recebe eventos fictícios de integrações, identifica falhas repetidas "
            "e abre incidentes para acompanhamento."
        ),
        lifespan=lifespan,
    )
    app.state.incident_service = service
    app.state.incident_assistant = incident_assistant

    def get_service() -> IncidentService:
        return app.state.incident_service

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.post(
        "/api/v1/events",
        response_model=EventProcessingResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["events"],
    )
    def receive_event(
        payload: EventCreate,
        service: IncidentService = Depends(get_service),
    ) -> EventProcessingResponse:
        event = EventData(
            event_id=payload.event_id,
            integration=payload.integration,
            status=payload.status,
            message=payload.message,
            occurred_at=payload.occurred_at,
            error_code=payload.error_code,
        )
        result = service.process_event(event)
        return EventProcessingResponse(**asdict(result))

    @app.get(
        "/api/v1/incidents",
        response_model=list[IncidentResponse],
        tags=["incidents"],
    )
    def list_incidents(
        service: IncidentService = Depends(get_service),
        incident_status: Annotated[
            Literal["open", "closed"] | None,
            Query(alias="status"),
        ] = None,
    ) -> list[dict[str, object]]:
        return service.list_incidents(incident_status)

    @app.get(
        "/api/v1/incidents/{incident_id}",
        response_model=IncidentResponse,
        tags=["incidents"],
    )
    def get_incident(
        incident_id: int,
        service: IncidentService = Depends(get_service),
    ) -> dict[str, object]:
        try:
            return service.get_incident(incident_id)
        except IncidentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch(
        "/api/v1/incidents/{incident_id}/close",
        response_model=IncidentResponse,
        tags=["incidents"],
    )
    def close_incident(
        incident_id: int,
        payload: CloseIncidentRequest,
        service: IncidentService = Depends(get_service),
    ) -> dict[str, object]:
        try:
            return service.close_incident(incident_id, payload.resolution)
        except IncidentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post(
        "/api/v1/incidents/{incident_id}/ai-analysis",
        response_model=IncidentAnalysisResponse,
        tags=["incidents", "optional-ai"],
    )
    def analyze_incident(
        incident_id: int,
        service: IncidentService = Depends(get_service),
    ) -> IncidentAnalysisResponse:
        assistant: IncidentAssistant | None = app.state.incident_assistant
        if assistant is None:
            raise HTTPException(
                status_code=503,
                detail="Integração opcional de IA não configurada.",
            )
        try:
            incident = service.get_incident(incident_id)
        except IncidentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            analysis = assistant.analyze(incident)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="O provedor de IA não conseguiu analisar o incidente.",
            ) from exc
        return IncidentAnalysisResponse(
            incident_id=incident_id,
            summary=analysis.summary,
            suggested_investigation=analysis.suggested_investigation,
            disclaimer=(
                "Sugestão gerada por IA. Confira as informações antes de executar qualquer ação."
            ),
        )

    return app


app = create_app()
