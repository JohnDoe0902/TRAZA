"""CP-01 a CP-04 (sección 17) y RF-02, RF-03, RF-04, RNF-04 sobre la API JSON."""

import re
import threading
import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.errors import NotAuthorized
from backend.models import Notification, OutboxJob, Ticket, TicketEvent, User
from backend.models.enums import (
    ActorType,
    EventType,
    JobStatus,
    JobType,
    MessageType,
    NotificationStatus,
    Role,
    TicketStatus,
)
from backend.repositories import outbox_repository
from backend.schemas.ticket import TicketCreate
from backend.services import ticket_service
from tests.helpers import TEST_PASSWORD_HASH, VALID_TICKET, count_rows

CODE_PATTERN = re.compile(r"^TRZ-\d{4,}$")

MakeUser = Callable[..., User]
Login = Callable[[User], TestClient]


def _create_ticket(db: Session, requester: User, **overrides: str) -> Ticket:
    return ticket_service.create_ticket(
        db, requester, TicketCreate.model_validate({**VALID_TICKET, **overrides})
    )


# --- CP-01 · Alta correcta ---------------------------------------------------------------


def test_cp01_alta_correcta_crea_ticket_evento_y_outbox(
    db: Session, make_user: MakeUser, login: Login
) -> None:
    requester = make_user(Role.REQUESTER)
    client = login(requester)

    response = client.post("/api/tickets", json=VALID_TICKET)

    assert response.status_code == 201, response.text
    body = response.json()
    assert CODE_PATTERN.match(body["public_code"])
    assert body["status"] == TicketStatus.PENDIENTE
    assert body["priority"] is None  # se clasifica después, en el worker

    ticket = db.scalars(select(Ticket).where(Ticket.public_code == body["public_code"])).one()
    assert ticket.requester_id == requester.id
    assert ticket.title == VALID_TICKET["title"]
    assert ticket.status == TicketStatus.PENDIENTE
    assert ticket.version == 1

    events = db.scalars(select(TicketEvent).where(TicketEvent.ticket_id == ticket.id)).all()
    assert len(events) == 1
    event = events[0]
    assert event.event_type == EventType.TICKET_CREATED
    assert event.actor_type == ActorType.USER
    assert event.actor_id == requester.id
    assert event.old_state is None
    assert event.new_state == TicketStatus.PENDIENTE
    assert isinstance(event.correlation_id, uuid.UUID)
    assert event.created_at is not None

    jobs = db.scalars(select(OutboxJob).where(OutboxJob.ticket_id == ticket.id)).all()
    assert [job.job_type for job in jobs] == [JobType.CLASSIFY_TICKET]
    assert jobs[0].status == JobStatus.PENDING
    assert jobs[0].payload_safe_json == {
        "ticket_id": ticket.id,
        "correlation_id": str(event.correlation_id),
    }


def test_cp01_solicitante_con_whatsapp_tambien_encola_mensaje_a1(
    db: Session, make_user: MakeUser
) -> None:
    requester = make_user(Role.REQUESTER, whatsapp_opt_in=True)

    ticket = _create_ticket(db, requester)

    jobs = db.scalars(select(OutboxJob).where(OutboxJob.ticket_id == ticket.id)).all()
    assert [job.job_type for job in jobs] == [JobType.CLASSIFY_TICKET, JobType.SEND_NOTIFICATION]
    notification = db.scalars(select(Notification).where(Notification.ticket_id == ticket.id)).one()
    assert notification.message_type == MessageType.A1
    assert notification.recipient_user_id == requester.id
    assert notification.status == NotificationStatus.PENDING  # nada se envía en el alta
    assert ticket.public_code in notification.body
    notification_payload = jobs[1].payload_safe_json
    assert notification_payload["notification_id"] == notification.id
    # El payload no lleva datos personales (RN-14): ni teléfono, ni correo, ni nombre.
    payload_text = str(notification_payload)
    assert requester.phone_e164 not in payload_text
    assert requester.email not in payload_text
    assert requester.full_name not in payload_text


def test_cp01_solicitante_sin_whatsapp_no_recibe_mensajes(db: Session, make_user: MakeUser) -> None:
    ticket = _create_ticket(db, make_user(Role.REQUESTER, whatsapp_opt_in=False))

    jobs = db.scalars(select(OutboxJob).where(OutboxJob.ticket_id == ticket.id)).all()
    assert [job.job_type for job in jobs] == [JobType.CLASSIFY_TICKET]
    assert db.scalars(select(Notification).where(Notification.ticket_id == ticket.id)).all() == []


def test_rnf04_falla_al_encolar_revierte_ticket_y_evento(
    db: Session, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    requester = make_user(Role.REQUESTER)
    before = count_rows(db)

    def failing_add(db: Session, job: OutboxJob) -> OutboxJob:
        raise RuntimeError("falla simulada al escribir en outbox_jobs")

    monkeypatch.setattr(outbox_repository, "add", failing_add)

    with pytest.raises(RuntimeError):
        _create_ticket(db, requester)

    assert count_rows(db) == before


def test_rf02_solo_el_solicitante_registra_tickets(make_user: MakeUser, login: Login) -> None:
    for role in (Role.TECHNICIAN, Role.ADMIN):
        response = login(make_user(role)).post("/api/tickets", json=VALID_TICKET)
        assert response.status_code == 403


def test_alta_sin_sesion_responde_401(client: TestClient, db: Session) -> None:
    before = count_rows(db)
    assert client.post("/api/tickets", json=VALID_TICKET).status_code == 401
    assert count_rows(db) == before


# --- CP-02 · Formulario inválido -----------------------------------------------------------


def test_cp02_descripcion_vacia_422_sin_guardar(
    db: Session, make_user: MakeUser, login: Login
) -> None:
    client = login(make_user(Role.REQUESTER))
    before = count_rows(db)

    response = client.post("/api/tickets", json={**VALID_TICKET, "description": ""})

    assert response.status_code == 422
    fields = {tuple(error["loc"]) for error in response.json()["detail"]}
    assert ("body", "description") in fields
    assert count_rows(db) == before


@pytest.mark.parametrize(
    "payload",
    [
        {"description": VALID_TICKET["description"]},  # falta el título
        {**VALID_TICKET, "title": "Hola"},
        {**VALID_TICKET, "description": "x" * 2001},
        {**VALID_TICKET, "location": "x" * 121},
    ],
)
def test_cp02_otros_datos_invalidos_422_sin_guardar(
    db: Session, make_user: MakeUser, login: Login, payload: dict[str, str]
) -> None:
    client = login(make_user(Role.REQUESTER))
    before = count_rows(db)

    assert client.post("/api/tickets", json=payload).status_code == 422
    assert count_rows(db) == before


# --- CP-03 · Permisos por objeto -----------------------------------------------------------


def test_cp03_solicitante_pide_ticket_ajeno_403(
    db: Session, make_user: MakeUser, login: Login
) -> None:
    owner = make_user(Role.REQUESTER)
    ticket = _create_ticket(db, owner, title="Proyector del aula 105 apagado")
    intruder = login(make_user(Role.REQUESTER))

    response = intruder.get(f"/api/tickets/{ticket.public_code}")

    assert response.status_code == 403
    assert "Proyector" not in response.text  # nunca datos de otro
    assert ticket.public_code not in response.text


def test_cp03_solicitante_ve_su_propio_ticket(
    db: Session, make_user: MakeUser, login: Login
) -> None:
    owner = make_user(Role.REQUESTER)
    ticket = _create_ticket(db, owner)

    response = login(owner).get(f"/api/tickets/{ticket.public_code}")

    assert response.status_code == 200
    assert response.json()["public_code"] == ticket.public_code


def test_cp03_tecnico_solo_ve_tickets_asignados(
    db: Session, make_user: MakeUser, login: Login
) -> None:
    ticket = _create_ticket(db, make_user(Role.REQUESTER))
    assigned = make_user(Role.TECHNICIAN)
    other = make_user(Role.TECHNICIAN)
    ticket.assigned_technician_id = assigned.id
    db.flush()

    assert login(assigned).get(f"/api/tickets/{ticket.public_code}").status_code == 200
    assert login(other).get(f"/api/tickets/{ticket.public_code}").status_code == 403


def test_cp03_admin_ve_cualquier_ticket(db: Session, make_user: MakeUser, login: Login) -> None:
    ticket = _create_ticket(db, make_user(Role.REQUESTER))
    response = login(make_user(Role.ADMIN)).get(f"/api/tickets/{ticket.public_code}")
    assert response.status_code == 200


def test_cp03_servicio_lanza_not_authorized(db: Session, make_user: MakeUser) -> None:
    ticket = _create_ticket(db, make_user(Role.REQUESTER))
    with pytest.raises(NotAuthorized):
        ticket_service.get_ticket_for_user(db, make_user(Role.REQUESTER), ticket.public_code)


def test_ticket_inexistente_404(make_user: MakeUser, login: Login) -> None:
    response = login(make_user(Role.ADMIN)).get("/api/tickets/TRZ-999999")
    assert response.status_code == 404


# --- RF-04 · Listado según rol ---------------------------------------------------------------


def test_rf04_listado_segun_rol(db: Session, make_user: MakeUser, login: Login) -> None:
    requester_a = make_user(Role.REQUESTER)
    requester_b = make_user(Role.REQUESTER)
    technician = make_user(Role.TECHNICIAN)
    ticket_a1 = _create_ticket(db, requester_a)
    ticket_a2 = _create_ticket(db, requester_a)
    ticket_b = _create_ticket(db, requester_b)
    ticket_b.assigned_technician_id = technician.id
    db.flush()

    def codes(client: TestClient) -> set[str]:
        response = client.get("/api/tickets")
        assert response.status_code == 200
        return {item["public_code"] for item in response.json()}

    assert codes(login(requester_a)) == {ticket_a1.public_code, ticket_a2.public_code}
    assert codes(login(requester_b)) == {ticket_b.public_code}
    assert codes(login(technician)) == {ticket_b.public_code}
    admin_codes = codes(login(make_user(Role.ADMIN)))
    assert {ticket_a1.public_code, ticket_a2.public_code, ticket_b.public_code} <= admin_codes


def test_rf04_filtro_por_estado(db: Session, make_user: MakeUser, login: Login) -> None:
    requester = make_user(Role.REQUESTER)
    _create_ticket(db, requester)
    client = login(requester)

    assert len(client.get("/api/tickets", params={"status": "PENDIENTE"}).json()) == 1
    assert client.get("/api/tickets", params={"status": "CERRADO"}).json() == []
    assert client.get("/api/tickets", params={"status": "INVENTADO"}).status_code == 422


# --- CP-04 · Código único con altas concurrentes ---------------------------------------------


def test_cp04_codigos_unicos_con_altas_concurrentes(engine: Engine) -> None:
    """Varios hilos registran tickets a la vez, cada uno con su propia conexión y transacción.

    Ninguna transacción se confirma: cada hilo revierte al final, así que no queda nada en la
    base (la secuencia sí avanza, como en producción).
    """
    threads_count, tickets_per_thread = 8, 5
    barrier = threading.Barrier(threads_count)
    codes: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            with engine.connect() as connection:
                transaction = connection.begin()
                session = Session(
                    bind=connection,
                    join_transaction_mode="create_savepoint",
                    expire_on_commit=False,
                )
                try:
                    requester = User(
                        full_name="Solicitante concurrente",
                        email=f"concurrente-{uuid.uuid4().hex}@traza.test",
                        password_hash=TEST_PASSWORD_HASH,
                        role=Role.REQUESTER,
                    )
                    session.add(requester)
                    session.flush()
                    barrier.wait(timeout=30)
                    for _ in range(tickets_per_thread):
                        ticket = _create_ticket(session, requester)
                        with lock:
                            codes.append(ticket.public_code)
                finally:
                    session.close()
                    transaction.rollback()
        except BaseException as exc:  # el hilo no puede propagar la excepción a pytest
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert errors == []
    assert len(codes) == threads_count * tickets_per_thread
    assert len(set(codes)) == len(codes), "hay códigos duplicados"
    assert all(CODE_PATTERN.match(code) for code in codes)


def test_cp04_generador_de_codigos_sin_duplicados_entre_conexiones(engine: Engine) -> None:
    threads_count, codes_per_thread = 10, 20
    barrier = threading.Barrier(threads_count)
    codes: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        with Session(engine) as session:
            barrier.wait(timeout=30)
            generated = [
                ticket_service.generate_public_code(session) for _ in range(codes_per_thread)
            ]
            session.rollback()
        with lock:
            codes.extend(generated)

    threads = [threading.Thread(target=worker) for _ in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert len(codes) == threads_count * codes_per_thread
    assert len(set(codes)) == len(codes)


def test_cp04_altas_sucesivas_reciben_codigos_distintos_y_crecientes(
    db: Session, make_user: MakeUser
) -> None:
    requester = make_user(Role.REQUESTER)
    codes = [_create_ticket(db, requester).public_code for _ in range(5)]

    numbers = [int(code.removeprefix("TRZ-")) for code in codes]
    assert numbers == sorted(numbers)
    assert len(set(codes)) == 5


def test_cp04_la_base_rechaza_un_codigo_duplicado(db: Session, make_user: MakeUser) -> None:
    requester = make_user(Role.REQUESTER)
    existing = _create_ticket(db, requester)

    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            Ticket(
                public_code=existing.public_code,
                requester_id=requester.id,
                title="Duplicado",
                description="Ticket con el código repetido",
                status=TicketStatus.PENDIENTE,
            )
        )
        db.flush()
