from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai import IncidentAnalysis
from app.database import Database
from app.main import create_app
from app.services import IncidentService


@pytest.fixture
def database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


@pytest.fixture
def service(database: Database) -> IncidentService:
    return IncidentService(database)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(tmp_path / "api-test.db")
    with TestClient(app) as test_client:
        yield test_client


class FakeIncidentAssistant:
    def analyze(self, incident: dict[str, object]) -> IncidentAnalysis:
        return IncidentAnalysis(
            summary=f"Foram detectadas {incident['occurrence_count']} falhas repetidas.",
            suggested_investigation=[
                "Verificar a disponibilidade do sistema de destino.",
                "Conferir os logs da integração no período do incidente.",
            ],
        )


@pytest.fixture
def ai_client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(
        tmp_path / "ai-api-test.db",
        incident_assistant=FakeIncidentAssistant(),
    )
    with TestClient(app) as test_client:
        yield test_client
