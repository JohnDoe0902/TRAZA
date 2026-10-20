"""Páginas de la Fase 2: bitácora y acciones en el detalle, y el simulador de WhatsApp."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.core.config import Settings, get_settings
from backend.models import Ticket, User
from backend.models.enums import MessageType, Role, TicketStatus
from backend.services import simulator_service
from backend.workers.process_outbox import drain
from tests.helpers import (
    RESOLUTION_TEXT,
    Actors,
    assigned_ticket,
    fake_providers,
    in_progress_ticket,
    new_ticket,
    notifications_of,
    pending_confirmation_ticket,
)

MakeUser = Callable[..., User]
Login = Callable[[User], TestClient]


def test_detalle_muestra_bitacora_en_espanol(db: Session, actors: Actors, login: Login) -> None:
    ticket = in_progress_ticket(db, actors)

    page = login(actors.requester).get(f"/tickets/{ticket.public_code}").text

    assert "Bitácora" in page
    assert "Solicitud registrada" in page
    assert "Técnico asignado" in page
    assert "Asignado → En proceso" in page
    assert actors.technician.full_name in page


def test_acciones_segun_rol_y_estado(db: Session, actors: Actors, login: Login) -> None:
    ticket = assigned_ticket(db, actors)
    url = f"/tickets/{ticket.public_code}"

    assert "Iniciar atención" in login(actors.technician).get(url).text
    admin_page = login(actors.admin).get(url).text
    assert "Reasignar" in admin_page
    assert "Iniciar atención" not in admin_page
    requester_page = login(actors.requester).get(url).text
    assert "Iniciar atención" not in requester_page
    assert "Reasignar" not in requester_page
    assert "¿El problema quedó solucionado?" not in requester_page


def test_flujo_web_de_tecnico_y_solicitante(db: Session, actors: Actors, login: Login) -> None:
    ticket = assigned_ticket(db, actors)
    url = f"/tickets/{ticket.public_code}"
    technician = login(actors.technician)

    response = technician.post(f"{url}/iniciar", data={"version": ticket.version})
    assert "Atención iniciada." in response.text
    db.refresh(ticket)
    response = technician.post(
        f"{url}/resolver", data={"resolution_text": RESOLUTION_TEXT, "version": ticket.version}
    )
    assert "Solución registrada" in response.text

    requester = login(actors.requester)
    page = requester.get(url).text
    assert "¿El problema quedó solucionado?" in page
    response = requester.post(f"{url}/confirmar", data={"answer": "YES"})
    assert "El ticket quedó cerrado." in response.text
    db.refresh(ticket)
    assert ticket.status == TicketStatus.CERRADO


def test_solucion_corta_por_web_muestra_error_y_no_cambia(
    db: Session, actors: Actors, login: Login
) -> None:
    ticket = in_progress_ticket(db, actors)

    response = login(actors.technician).post(
        f"/tickets/{ticket.public_code}/resolver",
        data={"resolution_text": "ok", "version": ticket.version},
    )

    assert "Debe tener al menos 10 caracteres." in response.text
    db.refresh(ticket)
    assert ticket.status == TicketStatus.EN_PROCESO


def test_formulario_con_version_vieja_muestra_aviso(
    db: Session, actors: Actors, login: Login
) -> None:
    ticket = assigned_ticket(db, actors)

    response = login(actors.technician).post(
        f"/tickets/{ticket.public_code}/iniciar", data={"version": ticket.version - 1}
    )

    assert "modificado por otra persona" in response.text
    db.refresh(ticket)
    assert ticket.status == TicketStatus.ASIGNADO


def test_tecnico_no_asignado_no_puede_actuar_por_web(
    db: Session, actors: Actors, login: Login
) -> None:
    ticket = assigned_ticket(db, actors)
    response = login(actors.other_technician).post(
        f"/tickets/{ticket.public_code}/iniciar", data={"version": ticket.version}
    )
    assert response.status_code == 403


def test_lista_filtra_por_prioridad_y_marca_revision(
    db: Session, actors: Actors, login: Login
) -> None:
    critical = new_ticket(db, actors.requester)
    security = new_ticket(
        db,
        actors.requester,
        title="Correo sospechoso",
        description="Posible exposición de credenciales por un correo sospechoso",
    )
    drain(db, providers=fake_providers())
    client = login(actors.admin)

    page = client.get("/tickets", params={"prioridad": "CRITICA"}).text
    assert critical.public_code in page
    assert security.public_code not in page
    assert "Revisión" in client.get("/tickets").text


# --- Simulador ------------------------------------------------------------------------------


def _answer_question(db: Session, actors: Actors, client: TestClient, answer: str) -> int:
    ticket = pending_confirmation_ticket(db, actors)
    drain(db, providers=fake_providers())
    question = next(n for n in notifications_of(db, ticket) if n.message_type == MessageType.A3)
    client.post("/simulador/responder", data={"notification_id": question.id, "answer": answer})
    db.refresh(ticket)
    return ticket.id


def test_simulador_muestra_chat_y_botones(db: Session, actors: Actors, login: Login) -> None:
    ticket = pending_confirmation_ticket(db, actors)
    client = login(actors.requester)

    before = client.get("/simulador").text
    assert "En cola" in before
    assert "Sí, se solucionó" not in before  # aún no se envió la pregunta

    drain(db, providers=fake_providers())
    page = client.get("/simulador").text
    assert ticket.public_code in page
    assert "¿El problema quedó solucionado?" in page
    assert "Sí, se solucionó" in page
    assert actors.requester.phone_e164 not in page  # teléfono enmascarado


def test_simulador_si_cierra_el_ticket(db: Session, actors: Actors, login: Login) -> None:
    ticket_id = _answer_question(db, actors, login(actors.requester), "YES")
    assert db.get(Ticket, ticket_id).status == TicketStatus.CERRADO


def test_simulador_doble_clic_es_un_solo_cambio(db: Session, actors: Actors, login: Login) -> None:
    client = login(actors.requester)
    ticket = pending_confirmation_ticket(db, actors)
    drain(db, providers=fake_providers())
    question = next(n for n in notifications_of(db, ticket) if n.message_type == MessageType.A3)

    for _ in range(2):
        client.post("/simulador/responder", data={"notification_id": question.id, "answer": "NO"})

    db.refresh(ticket)
    assert ticket.status == TicketStatus.REABIERTO
    assert ticket.reopen_count == 1


def test_simulador_admin_ve_chats_y_tecnico_recibe_a8(
    db: Session, actors: Actors, login: Login
) -> None:
    client = login(actors.requester)
    _answer_question(db, actors, client, "NO")
    drain(db, providers=fake_providers())

    admin = login(actors.admin)
    page = admin.get("/simulador", params={"usuario": actors.technician.id}).text
    assert "El solicitante indicó que el problema" in page


def test_simulador_no_permite_ver_chat_ajeno(
    db: Session, actors: Actors, make_user: MakeUser, login: Login
) -> None:
    ticket = pending_confirmation_ticket(db, actors)
    drain(db, providers=fake_providers())
    question = next(n for n in notifications_of(db, ticket) if n.message_type == MessageType.A3)
    intruder = login(make_user(Role.REQUESTER, whatsapp_opt_in=True))

    response = intruder.post(
        "/simulador/responder", data={"notification_id": question.id, "answer": "YES"}
    )

    assert response.status_code == 403
    db.refresh(ticket)
    assert ticket.status == TicketStatus.PENDIENTE_CONFIRMACION


def test_simulador_deshabilitado_fuera_de_desarrollo(
    actors: Actors, login: Login, monkeypatch: pytest.MonkeyPatch
) -> None:
    production = Settings(**{**get_settings().model_dump(), "app_env": "production"})
    monkeypatch.setattr(simulator_service, "get_settings", lambda: production)

    response = login(actors.admin).get("/simulador")

    assert response.status_code == 404
