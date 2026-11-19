"""/health con la base, el latido del worker y la cola (sección 15)."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.core.clock import utcnow
from backend.models import WorkerHeartbeat
from backend.models.enums import JobStatus
from backend.repositories import health_repository, heartbeat_repository
from backend.services import health_service
from backend.services.uow import atomic
from backend.workers import process_outbox
from tests.helpers import Actors, fake_providers, jobs_of, new_ticket


def beat(db: Session, seconds_ago: int, worker_id: str = "pc-prueba:1") -> None:
    when = utcnow() - timedelta(seconds=seconds_ago)
    health_service.record_heartbeat(db, worker_id, started_at=when, now=when)


# --- Cola --------------------------------------------------------------------------------------


def test_health_cuenta_los_trabajos_pendientes_y_fallidos(
    db: Session, client: TestClient, actors: Actors
) -> None:
    ticket = new_ticket(db, actors.requester)
    jobs = jobs_of(db, ticket)
    # Marcamos uno como fallido para ver que se cuenta aparte
    with atomic(db):
        jobs[0].status = JobStatus.FAILED

    response = client.get("/health")

    assert response.json()["queue"] == {"pending": len(jobs) - 1, "failed": 1}


def test_health_con_la_cola_vacia(client: TestClient) -> None:
    assert client.get("/health").json()["queue"] == {"pending": 0, "failed": 0}


# --- Latido del worker -------------------------------------------------------------------------


def test_health_ok_con_el_worker_vivo(db: Session, client: TestClient) -> None:
    beat(db, seconds_ago=5)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["worker"]["status"] == "ok"
    assert body["worker"]["last_seen_at"] is not None


def test_health_detecta_el_worker_detenido(db: Session, client: TestClient) -> None:
    beat(db, seconds_ago=61)

    response = client.get("/health")

    # La web sigue atendiendo así que no es 503, pero se marca como degradado
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["worker"]["status"] == "down"


def test_health_sin_ningun_latido(client: TestClient) -> None:
    body = client.get("/health").json()

    assert body["status"] == "degraded"
    assert body["worker"] == {"status": "never_seen", "last_seen_at": None}


def test_con_varios_workers_cuenta_el_mas_reciente(db: Session, client: TestClient) -> None:
    beat(db, seconds_ago=300, worker_id="pc-vieja:1")
    beat(db, seconds_ago=3, worker_id="pc-nueva:2")

    assert client.get("/health").json()["worker"]["status"] == "ok"


def test_el_latido_actualiza_la_misma_fila(db: Session) -> None:
    beat(db, seconds_ago=30)
    beat(db, seconds_ago=1)

    rows = db.query(WorkerHeartbeat).filter_by(worker_id="pc-prueba:1").all()
    assert len(rows) == 1
    assert utcnow() - rows[0].last_seen_at < timedelta(seconds=5)


def test_cada_ciclo_del_worker_deja_su_latido(db: Session, client: TestClient) -> None:
    identity = process_outbox.WorkerIdentity(worker_id="pc-worker:7")

    process_outbox.process_batch(db, providers=fake_providers(), identity=identity)

    assert db.get(WorkerHeartbeat, "pc-worker:7") is not None
    assert client.get("/health").json()["worker"]["status"] == "ok"


def test_si_el_latido_falla_la_cola_sigue(
    db: Session, actors: Actors, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise OperationalError("INSERT", {}, Exception("falla simulada"))

    monkeypatch.setattr(heartbeat_repository, "upsert", broken)
    new_ticket(db, actors.requester)

    assert process_outbox.process_batch(db, providers=fake_providers()) > 0


# --- Base caída --------------------------------------------------------------------------------


def test_health_avisa_si_la_base_no_responde(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def base_caida(db: Session) -> None:
        raise OperationalError("SELECT 1", {}, Exception("sin conexión"))

    monkeypatch.setattr(health_repository, "ping", base_caida)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "error"}
