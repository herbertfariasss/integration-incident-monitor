from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, status

from app.ai import IncidentAssistant, OpenAICompatibleIncidentAssistant
from app.database import Database
from app.models import EventData
from app.schemas import (
    AttemptResponse,
    CloseIncidentRequest,
    DeliveryResponse,
    EventCreate,
    EventProcessingResponse,
    EventResponse,
    HealthResponse,
    IncidentAnalysisResponse,
    IncidentResponse,
)
from app.services import IncidentNotFoundError, IncidentService, ReprocessConflictError


def create_app(
    database_url: str | None = None,
    *,
    incident_assistant: IncidentAssistant | None = None,
) -> FastAPI:
    database = Database(database_url)
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
        try:
            with database.connection() as connection:
                connection.execute("SELECT 1")
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Banco indisponível") from exc
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
        result = service.process_event(event, payload.simulated_failures)
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
        integration: str | None = Query(default=None, min_length=1, max_length=100),
        error_code: str | None = Query(default=None, min_length=1, max_length=100),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> list[dict[str, object]]:
        return service.list_incidents(incident_status, integration, error_code, limit, offset)

    @app.get("/api/v1/incidents/counts", tags=["incidents"])
    def incident_counts(service: IncidentService = Depends(get_service)) -> dict[str, int]:
        return service.counts()

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

    @app.get("/api/v1/incidents/{incident_id}/events", response_model=list[EventResponse], tags=["incidents"])
    def incident_events(
        incident_id: int, limit: int = Query(default=100, ge=1, le=100),
        offset: int = Query(default=0, ge=0), service: IncidentService = Depends(get_service),
    ) -> list[dict]:
        try:
            return service.get_timeline(incident_id, limit, offset)
        except IncidentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/v1/incidents/{incident_id}/deliveries", response_model=list[DeliveryResponse], tags=["deliveries"])
    def incident_deliveries(
        incident_id: int, limit: int = Query(default=100, ge=1, le=100),
        offset: int = Query(default=0, ge=0), service: IncidentService = Depends(get_service),
    ) -> list[dict]:
        try:
            return service.list_deliveries(incident_id, limit, offset)
        except IncidentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/v1/deliveries/{delivery_id}/attempts", response_model=list[AttemptResponse], tags=["deliveries"])
    def delivery_attempts(
        delivery_id: int, limit: int = Query(default=100, ge=1, le=100),
        offset: int = Query(default=0, ge=0), service: IncidentService = Depends(get_service),
    ) -> list[dict]:
        try:
            return service.list_attempts(delivery_id, limit, offset)
        except IncidentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/v1/deliveries/{delivery_id}/reprocess", response_model=DeliveryResponse, tags=["deliveries"])
    def reprocess_delivery(
        delivery_id: int, service: IncidentService = Depends(get_service),
    ) -> dict:
        try:
            return service.reprocess(delivery_id)
        except IncidentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ReprocessConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

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
