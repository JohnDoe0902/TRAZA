"""/health con el estado de la base y de la cola (sección 15)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.models.enums import JobStatus
from backend.repositories import health_repository
from backend.services.uow import atomic
from tests.helpers import Actors, jobs_of, new_ticket


def test_health_cuenta_los_trabajos_pendientes_y_fallidos(
    db: Session, client: TestClient, actors: Actors
) -> None:
    ticket = new_ticket(db, actors.requester)
    jobs = jobs_of(db, ticket)
    # Marcamos uno como fallido para ver que se cuenta aparte
    with atomic(db):
        jobs[0].status = JobStatus.FAILED

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "queue": {"pending": len(jobs) - 1, "failed": 1},
    }


def test_health_con_la_cola_vacia(client: TestClient) -> None:
    response = client.get("/health")

    assert response.json()["queue"] == {"pending": 0, "failed": 0}


def test_health_avisa_si_la_base_no_responde(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def base_caida(db: Session) -> None:
        raise OperationalError("SELECT 1", {}, Exception("sin conexión"))

    monkeypatch.setattr(health_repository, "ping", base_caida)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "error"}
