"""Confirmación del solicitante (sección 9.2, RF-15, RF-16, reglas 1 y 7).

Las tres entradas (web, simulador y, en la Fase 4, webhook de WhatsApp) pasan por
`register_answer`. Una respuesta repetida o tardía no cambia nada y deja
DUPLICATE_ANSWER_IGNORED.
"""

import uuid
from enum import StrEnum

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.errors import ConcurrencyConflict, NotAuthorized
from backend.models import Confirmation, Ticket, User
from backend.models.enums import (
    ConfirmationAnswer,
    ConfirmationSource,
    EventType,
    MessageType,
    TicketStatus,
)
from backend.repositories import confirmation_repository, ticket_repository, user_repository
from backend.services import audit_service, notification_service, ticket_service
from backend.services.uow import atomic


class AnswerOutcome(StrEnum):
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    IGNORED = "IGNORED"


def simulator_event_id(notification_id: int, answer: ConfirmationAnswer) -> str:
    """Id estable del botón del simulador: pulsar dos veces lo mismo es un duplicado."""
    return f"sim-{notification_id}-{answer.value}"


def register_answer(
    db: Session,
    *,
    ticket: Ticket,
    responder: User,
    answer: ConfirmationAnswer,
    source: ConfirmationSource,
    provider_event_id: str | None = None,
    notification_id: int | None = None,
) -> AnswerOutcome:
    if responder.id != ticket.requester_id:
        raise NotAuthorized("Solo el solicitante del ticket puede responder la confirmación.")

    if provider_event_id and confirmation_repository.get_by_provider_event_id(
        db, provider_event_id
    ):
        return _ignore(db, ticket, responder, source, provider_event_id, reason="duplicate")
    if ticket.status != TicketStatus.PENDIENTE_CONFIRMACION:
        return _ignore(db, ticket, responder, source, provider_event_id, reason="not_pending")

    confirmation_round = ticket.reopen_count + 1
    correlation_id = uuid.uuid4()
    try:
        with atomic(db):
            confirmation_repository.add(
                db,
                Confirmation(
                    ticket_id=ticket.id,
                    requester_id=responder.id,
                    notification_id=notification_id,
                    answer=answer,
                    source=source,
                    provider_event_id=provider_event_id,
                    confirmation_round=confirmation_round,
                ),
            )
            if answer == ConfirmationAnswer.YES:
                _accept(db, ticket, responder, source, correlation_id)
            else:
                _reject(db, ticket, responder, source, correlation_id)
    except (IntegrityError, ConcurrencyConflict):
        # Otra respuesta del mismo ciclo ganó la carrera: esta no produce un segundo cambio.
        ticket = ticket_repository.get_by_id(db, ticket.id) or ticket
        return _ignore(db, ticket, responder, source, provider_event_id, reason="duplicate")

    return AnswerOutcome.CLOSED if answer == ConfirmationAnswer.YES else AnswerOutcome.REOPENED


def _accept(
    db: Session,
    ticket: Ticket,
    requester: User,
    source: ConfirmationSource,
    correlation_id: uuid.UUID,
) -> None:
    audit_service.record_event(
        db,
        ticket=ticket,
        event_type=EventType.CONFIRMATION_ACCEPTED,
        actor=requester,
        correlation_id=correlation_id,
        details={"source": source.value},
    )
    ticket_service.transition(
        db, ticket, TicketStatus.CERRADO, requester, correlation_id=correlation_id
    )
    notification_service.enqueue(
        db,
        ticket=ticket,
        recipient=requester,
        message_type=MessageType.A4,
        correlation_id=correlation_id,
    )


def _reject(
    db: Session,
    ticket: Ticket,
    requester: User,
    source: ConfirmationSource,
    correlation_id: uuid.UUID,
) -> None:
    audit_service.record_event(
        db,
        ticket=ticket,
        event_type=EventType.CONFIRMATION_REJECTED,
        actor=requester,
        correlation_id=correlation_id,
        details={"source": source.value},
    )
    ticket_service.transition(
        db, ticket, TicketStatus.REABIERTO, requester, correlation_id=correlation_id
    )
    notification_service.enqueue(
        db,
        ticket=ticket,
        recipient=requester,
        message_type=MessageType.A5,
        correlation_id=correlation_id,
    )
    if ticket.assigned_technician_id is not None:
        technician = user_repository.get_by_id(db, ticket.assigned_technician_id)
        if technician is not None:
            notification_service.enqueue(
                db,
                ticket=ticket,
                recipient=technician,
                message_type=MessageType.A8,
                correlation_id=correlation_id,
            )


def _ignore(
    db: Session,
    ticket: Ticket,
    responder: User,
    source: ConfirmationSource,
    provider_event_id: str | None,
    *,
    reason: str,
) -> AnswerOutcome:
    with atomic(db):
        audit_service.record_event(
            db,
            ticket=ticket,
            event_type=EventType.DUPLICATE_ANSWER_IGNORED,
            actor=responder,
            correlation_id=uuid.uuid4(),
            details={
                "source": source.value,
                "provider_event_id": provider_event_id,
                "reason": reason,
            },
        )
    return AnswerOutcome.IGNORED
