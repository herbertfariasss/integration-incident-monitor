import os
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from app.ai import IncidentAnalysis
from app.database import Database
from app.main import create_app
from app.services import IncidentService


@pytest.fixture
def database() -> Iterator[Database]:
    admin_url = os.getenv(
        "TEST_DATABASE_ADMIN_URL", "postgresql://incident@localhost:55432/postgres"
    )
    name = "test_" + uuid4().hex
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    database = Database(admin_url.rsplit("/", 1)[0] + "/" + name)
    try:
        database.initialize()
        yield database
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def service(database: Database) -> IncidentService:
    return IncidentService(database)


@pytest.fixture
def client(database: Database) -> Iterator[TestClient]:
    with TestClient(create_app(database.url)) as test_client:
        yield test_client


class FakeIncidentAssistant:
    def analyze(self, incident: dict[str, object]) -> IncidentAnalysis:
        return IncidentAnalysis(
            summary=f"Foram detectadas {incident['occurrence_count']} falhas repetidas.",
            suggested_investigation=[
                "Verificar a disponibilidade do destino fictício.",
                "Conferir o histórico das tentativas de entrega.",
            ],
        )


@pytest.fixture
def ai_client(database: Database) -> Iterator[TestClient]:
    with TestClient(create_app(database.url, incident_assistant=FakeIncidentAssistant())) as test_client:
        yield test_client
