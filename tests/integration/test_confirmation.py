"""CP-12, CP-13, CP-14 y reglas 1 y 7: confirmación del solicitante."""

from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import utcnow
from backend.core.errors import NotAuthorized
from backend.models import Confirmation, User
from backend.models.enums import (
    ConfirmationAnswer,
    ConfirmationSource,
    EventType,
    MessageType,
    Role,
    TicketStatus,
)
from backend.services import ticket_service
from backend.services.confirmation_service import AnswerOutcome
from backend.workers.process_outbox import drain
from tests.helpers import (
    RESOLUTION_TEXT,
    Actors,
    answer,
    event_types,
    events_of,
    fake_providers,
    in_progress_ticket,
    notifications_of,
    pending_confirmation_ticket,
)

YES, NO = ConfirmationAnswer.YES, ConfirmationAnswer.NO
MakeUser = Callable[..., User]
Login = Callable[[User], TestClient]


def _confirmations(db: Session, ticket_id: int) -> list[Confirmation]:
    query = select(Confirmation).where(Confirmation.ticket_id == ticket_id)
    return list(db.scalars(query.order_by(Confirmation.id)))


def test_cp12_si_cierra_una_vez(db: Session, actors: Actors) -> None:
    ticket = pending_confirmation_ticket(db, actors)

    outcome = answer(db, ticket, actors.requester, YES)

    assert outcome == AnswerOutcome.CLOSED
    assert ticket.status == TicketStatus.CERRADO
    assert ticket.closed_at is not None
    assert event_types(db, ticket)[-2:] == [
        EventType.CONFIRMATION_ACCEPTED,
        EventType.TICKET_STATUS_CHANGED,
    ]
    closing = events_of(db, ticket, EventType.TICKET_STATUS_CHANGED)[-1]
    assert closing.new_state == TicketStatus.CERRADO
    assert closing.actor_id == actors.requester.id
    assert len(_confirmations(db, ticket.id)) == 1
    assert MessageType.A4 in [n.message_type for n in notifications_of(db, ticket)]


def test_cp13_no_reabre_y_avisa_al_tecnico(db: Session, actors: Actors) -> None:
    ticket = pending_confirmation_ticket(db, actors)

    outcome = answer(db, ticket, actors.requester, NO)

    assert outcome == AnswerOutcome.REOPENED
    assert ticket.status == TicketStatus.REABIERTO
    assert ticket.reopen_count == 1
    assert ticket.closed_at is None
    assert event_types(db, ticket)[-2:] == [
        EventType.CONFIRMATION_REJECTED,
        EventType.TICKET_REOPENED,
    ]
    reopened = events_of(db, ticket, EventType.TICKET_REOPENED)[0]
    assert reopened.old_state == TicketStatus.PENDIENTE_CONFIRMACION
    assert reopened.new_state == TicketStatus.REABIERTO
    assert reopened.safe_details_json["reopen_number"] == 1

    notifications = notifications_of(db, ticket)
    tech_notice = [n for n in notifications if n.message_type == MessageType.A8]
    assert len(tech_notice) == 1
    assert tech_notice[0].recipient_user_id == actors.technician.id
    assert MessageType.A5 in [n.message_type for n in notifications]


def test_cp14_misma_respuesta_dos_veces_un_solo_cambio(db: Session, actors: Actors) -> None:
    ticket = pending_confirmation_ticket(db, actors)
    event_id = "wamid.DUPLICADO-001"

    first = answer(
        db,
        ticket,
        actors.requester,
        YES,
        provider_event_id=event_id,
        source=ConfirmationSource.SIMULATOR,
    )
    second = answer(
        db,
        ticket,
        actors.requester,
        YES,
        provider_event_id=event_id,
        source=ConfirmationSource.SIMULATOR,
    )

    assert (first, second) == (AnswerOutcome.CLOSED, AnswerOutcome.IGNORED)
    assert ticket.status == TicketStatus.CERRADO
    assert len(_confirmations(db, ticket.id)) == 1
    closings = [
        e
        for e in events_of(db, ticket, EventType.TICKET_STATUS_CHANGED)
        if e.new_state == TicketStatus.CERRADO
    ]
    assert len(closings) == 1
    duplicate = events_of(db, ticket, EventType.DUPLICATE_ANSWER_IGNORED)
    assert len(duplicate) == 1
    assert duplicate[0].safe_details_json["reason"] == "duplicate"
    assert duplicate[0].safe_details_json["provider_event_id"] == event_id


def test_cp14_doble_envio_web_un_solo_cambio(db: Session, actors: Actors, login: Login) -> None:
    ticket = pending_confirmation_ticket(db, actors)
    client = login(actors.requester)
    url = f"/api/tickets/{ticket.public_code}/confirm"

    first = client.post(url, json={"answer": "NO"})
    second = client.post(url, json={"answer": "NO"})

    assert first.json() == {"result": "REOPENED", "status": "REABIERTO"}
    assert second.json() == {"result": "IGNORED", "status": "REABIERTO"}
    db.refresh(ticket)
    assert ticket.reopen_count == 1  # reabre exactamente una vez (RN-11)
    assert len(events_of(db, ticket, EventType.TICKET_REOPENED)) == 1
    assert len(events_of(db, ticket, EventType.DUPLICATE_ANSWER_IGNORED)) == 1


def test_respuesta_tardia_no_cambia_nada(db: Session, actors: Actors) -> None:
    ticket = pending_confirmation_ticket(db, actors)
    answer(db, ticket, actors.requester, YES)

    late = answer(db, ticket, actors.requester, NO)

    assert late == AnswerOutcome.IGNORED
    assert ticket.status == TicketStatus.CERRADO
    assert ticket.reopen_count == 0
    ignored = events_of(db, ticket, EventType.DUPLICATE_ANSWER_IGNORED)[0]
    assert ignored.safe_details_json["reason"] == "not_pending"


def test_respuesta_antes_de_la_solucion_no_cierra(db: Session, actors: Actors) -> None:
    ticket = in_progress_ticket(db, actors)
    assert answer(db, ticket, actors.requester, YES) == AnswerOutcome.IGNORED
    assert ticket.status == TicketStatus.EN_PROCESO


def test_solo_el_solicitante_del_ticket_responde(
    db: Session, actors: Actors, make_user: MakeUser
) -> None:
    ticket = pending_confirmation_ticket(db, actors)
    for intruder in (make_user(Role.REQUESTER), actors.technician, actors.admin):
        with pytest.raises(NotAuthorized):
            answer(db, ticket, intruder, YES)
    assert ticket.status == TicketStatus.PENDIENTE_CONFIRMACION
    assert _confirmations(db, ticket.id) == []


def test_confirmar_ticket_ajeno_por_api_403(
    db: Session, actors: Actors, make_user: MakeUser, login: Login
) -> None:
    ticket = pending_confirmation_ticket(db, actors)
    response = login(make_user(Role.REQUESTER)).post(
        f"/api/tickets/{ticket.public_code}/confirm", json={"answer": "YES"}
    )
    assert response.status_code == 403


def test_segundo_ciclo_tras_reapertura(db: Session, actors: Actors) -> None:
    """No → retoma → nueva solución → Sí: dos confirmaciones, rondas 1 y 2."""
    ticket = pending_confirmation_ticket(db, actors)
    answer(db, ticket, actors.requester, NO)
    ticket_service.start_work(db, ticket, actors.technician)
    ticket_service.propose_resolution(db, ticket, actors.technician, RESOLUTION_TEXT + " (2)")

    assert answer(db, ticket, actors.requester, YES) == AnswerOutcome.CLOSED

    rounds = [(c.confirmation_round, c.answer) for c in _confirmations(db, ticket.id)]
    assert rounds == [(1, NO), (2, YES)]
    assert ticket.status == TicketStatus.CERRADO
    assert ticket.reopen_count == 1


def test_regla1_el_silencio_no_cierra(db: Session, actors: Actors) -> None:
    ticket = pending_confirmation_ticket(db, actors)
    # El worker procesa todo lo pendiente "una semana después" y aun así nada cierra el ticket.
    drain(db, providers=fake_providers(), now=utcnow() + timedelta(days=7))
    db.refresh(ticket)
    assert ticket.status == TicketStatus.PENDIENTE_CONFIRMACION
    assert ticket.closed_at is None
