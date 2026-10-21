"""Lógica de negocio de tickets: alta, consulta, máquina de estados y atención técnica."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session

from backend.core.clock import utcnow
from backend.core.errors import (
    BusinessRuleViolation,
    ConcurrencyConflict,
    InvalidTransition,
    NotAuthorized,
    NotFound,
)
from backend.core.permissions import ensure_can_view_ticket, ticket_scope_for
from backend.models import OutboxJob, Ticket, TicketEvent, User
from backend.models.enums import EventType, JobType, MessageType, Priority, Role, TicketStatus
from backend.repositories import outbox_repository, ticket_repository, user_repository
from backend.schemas.ticket import TicketCreate
from backend.services import audit_service, notification_service
from backend.services.uow import atomic

TICKET_CODE_PREFIX = "TRZ-"
RESOLUTION_SUMMARY_LENGTH = 120


# --- Código público --------------------------------------------------------------------------


def format_ticket_code(number: int) -> str:
    """`TRZ-` + número con al menos 4 dígitos (RN-02): 1 → TRZ-0001, 12345 → TRZ-12345."""
    return f"{TICKET_CODE_PREFIX}{number:04d}"


def generate_public_code(db: Session) -> str:
    return format_ticket_code(ticket_repository.next_code_number(db))


# --- Máquina de estados (sección 8.2) --------------------------------------------------------


class ActorKind(StrEnum):
    """Papel de quien pide la transición respecto de ese ticket concreto."""

    ADMIN = "ADMIN"
    SYSTEM = "SYSTEM"
    ASSIGNED_TECHNICIAN = "ASSIGNED_TECHNICIAN"
    OWNER_REQUESTER = "OWNER_REQUESTER"


@dataclass(frozen=True)
class TransitionRule:
    allowed: frozenset[ActorKind]
    requires_reason: bool = False
    # Evento que registra el cambio de estado; None si el estado no cambia (reasignación).
    status_event: EventType | None = EventType.TICKET_STATUS_CHANGED


_S = TicketStatus
_K = ActorKind

TRANSITIONS: dict[tuple[TicketStatus, TicketStatus], TransitionRule] = {
    (_S.PENDIENTE, _S.ASIGNADO): TransitionRule(frozenset({_K.ADMIN, _K.SYSTEM})),
    (_S.ASIGNADO, _S.ASIGNADO): TransitionRule(
        frozenset({_K.ADMIN}), requires_reason=True, status_event=None
    ),
    # Reasignar un ticket en proceso lo devuelve a ASIGNADO: es un cambio de estado y deja su
    # evento (regla 3), aunque la tabla 8.2 solo menciona TICKET_ASSIGNED.
    (_S.EN_PROCESO, _S.ASIGNADO): TransitionRule(frozenset({_K.ADMIN}), requires_reason=True),
    (_S.ASIGNADO, _S.EN_PROCESO): TransitionRule(frozenset({_K.ASSIGNED_TECHNICIAN})),
    (_S.EN_PROCESO, _S.PENDIENTE_CONFIRMACION): TransitionRule(frozenset({_K.ASSIGNED_TECHNICIAN})),
    (_S.PENDIENTE_CONFIRMACION, _S.CERRADO): TransitionRule(frozenset({_K.OWNER_REQUESTER})),
    (_S.PENDIENTE_CONFIRMACION, _S.REABIERTO): TransitionRule(
        frozenset({_K.OWNER_REQUESTER}), status_event=EventType.TICKET_REOPENED
    ),
    (_S.REABIERTO, _S.EN_PROCESO): TransitionRule(frozenset({_K.ASSIGNED_TECHNICIAN})),
    (_S.REABIERTO, _S.ASIGNADO): TransitionRule(frozenset({_K.ADMIN}), requires_reason=True),
}


def actor_kinds(ticket: Ticket, actor: User | None) -> frozenset[ActorKind]:
    if actor is None:
        return frozenset({ActorKind.SYSTEM})
    if actor.role == Role.ADMIN:
        return frozenset({ActorKind.ADMIN})
    if actor.role == Role.TECHNICIAN and ticket.assigned_technician_id == actor.id:
        return frozenset({ActorKind.ASSIGNED_TECHNICIAN})
    if actor.role == Role.REQUESTER and ticket.requester_id == actor.id:
        return frozenset({ActorKind.OWNER_REQUESTER})
    return frozenset()


def validate_transition(
    ticket: Ticket,
    to_status: TicketStatus,
    actor: User | None,
    *,
    reason: str | None = None,
    expected_version: int | None = None,
) -> TransitionRule:
    """Comprueba tabla, actor, motivo y versión sin modificar nada.

    Orden: transición inexistente → 409; actor sin permiso → 403; versión vieja → 409.
    """
    rule = TRANSITIONS.get((ticket.status, to_status))
    if rule is None:
        raise InvalidTransition(f"No se puede pasar de {ticket.status.value} a {to_status.value}.")
    if not rule.allowed & actor_kinds(ticket, actor):
        raise NotAuthorized("No tienes permiso para realizar este cambio de estado.")
    if rule.requires_reason and not (reason and reason.strip()):
        raise BusinessRuleViolation("Este cambio requiere un motivo.")
    if expected_version is not None and expected_version != ticket.version:
        raise ConcurrencyConflict()
    if actor is None and to_status == TicketStatus.ASIGNADO and ticket.review_required:
        raise BusinessRuleViolation("El ticket requiere revisión del administrador.")
    if to_status == TicketStatus.PENDIENTE_CONFIRMACION and not ticket.resolution_text:
        raise BusinessRuleViolation("Debes registrar el texto de la solución.")
    return rule


def is_transition_allowed(ticket: Ticket, to_status: TicketStatus, actor: User | None) -> bool:
    """Para decidir qué acciones mostrar; no valida motivo ni versión."""
    rule = TRANSITIONS.get((ticket.status, to_status))
    return rule is not None and bool(rule.allowed & actor_kinds(ticket, actor))


def transition(
    db: Session,
    ticket: Ticket,
    to_status: TicketStatus,
    actor: User | None,
    *,
    correlation_id: uuid.UUID,
    reason: str | None = None,
    expected_version: int | None = None,
) -> TicketEvent | None:
    """Única puerta para cambiar `tickets.status` (regla 2).

    Valida contra la tabla 8.2 y escribe el evento del cambio en la transacción en curso.
    Si algo no es válido lanza un error de dominio y no modifica nada. No confirma: lo hace
    la operación que la llama, junto con sus propios eventos.
    """
    rule = validate_transition(
        ticket, to_status, actor, reason=reason, expected_version=expected_version
    )
    old_status = ticket.status
    now = utcnow()

    ticket.status = to_status
    if to_status == TicketStatus.EN_PROCESO and ticket.first_response_at is None:
        ticket.first_response_at = now
    if to_status == TicketStatus.CERRADO:
        ticket.closed_at = now
    if to_status == TicketStatus.REABIERTO:
        ticket.reopen_count += 1

    if rule.status_event is None:
        return None
    details: dict[str, object] = {}
    if reason:
        details["reason"] = reason
    if to_status == TicketStatus.REABIERTO:
        details["reopen_number"] = ticket.reopen_count
    return audit_service.record_event(
        db,
        ticket=ticket,
        event_type=rule.status_event,
        actor=actor,
        old_state=old_status,
        new_state=to_status,
        correlation_id=correlation_id,
        details=details,
    )


# --- Alta y consulta -------------------------------------------------------------------------


def create_ticket(db: Session, requester: User, data: TicketCreate) -> Ticket:
    """Registra un ticket (CU-02, sección 9.1).

    En una sola transacción: ticket en PENDIENTE, evento TICKET_CREATED, trabajo de
    clasificación y, si el solicitante aceptó WhatsApp, el mensaje A1. No llama a ningún
    servicio externo; la clasificación y los envíos los hace el worker.
    """
    if requester.role != Role.REQUESTER:
        raise NotAuthorized("Solo los solicitantes pueden registrar tickets.")

    correlation_id = uuid.uuid4()
    with atomic(db):
        ticket = ticket_repository.add(
            db,
            Ticket(
                public_code=generate_public_code(db),
                requester_id=requester.id,
                title=data.title,
                description=data.description,
                location=data.location,
                status=TicketStatus.PENDIENTE,
            ),
        )
        audit_service.record_event(
            db,
            ticket=ticket,
            event_type=EventType.TICKET_CREATED,
            actor=requester,
            new_state=TicketStatus.PENDIENTE,
            correlation_id=correlation_id,
        )
        outbox_repository.add(
            db,
            OutboxJob(
                ticket_id=ticket.id,
                job_type=JobType.CLASSIFY_TICKET,
                payload_safe_json={"ticket_id": ticket.id, "correlation_id": str(correlation_id)},
            ),
        )
        notification_service.enqueue(
            db,
            ticket=ticket,
            recipient=requester,
            message_type=MessageType.A1,
            correlation_id=correlation_id,
        )
    return ticket


def list_tickets_for_user(
    db: Session,
    user: User,
    *,
    status: TicketStatus | None = None,
    priority: Priority | None = None,
    review_required: bool | None = None,
) -> Sequence[Ticket]:
    """Lista según el rol (RF-04): solicitante, los suyos; técnico, asignados; admin, todos."""
    scope = ticket_scope_for(user)
    return ticket_repository.list_tickets(
        db,
        requester_id=scope.requester_id,
        technician_id=scope.technician_id,
        status=status,
        priority=priority,
        review_required=review_required,
    )


def get_ticket_for_user(db: Session, user: User, public_code: str) -> Ticket:
    """Detalle de un ticket con permiso por objeto: acceso indebido → 403."""
    ticket = ticket_repository.get_by_code(db, public_code.upper())
    if ticket is None:
        raise NotFound(f"No existe el ticket {public_code}.")
    ensure_can_view_ticket(user, ticket)
    return ticket


# --- Atención técnica ------------------------------------------------------------------------


def start_work(
    db: Session, ticket: Ticket, technician: User, *, expected_version: int | None = None
) -> Ticket:
    """El técnico asignado inicia (ASIGNADO) o retoma (REABIERTO) la atención."""
    with atomic(db):
        transition(
            db,
            ticket,
            TicketStatus.EN_PROCESO,
            technician,
            correlation_id=uuid.uuid4(),
            expected_version=expected_version,
        )
    return ticket


def propose_resolution(
    db: Session,
    ticket: Ticket,
    technician: User,
    resolution_text: str,
    *,
    expected_version: int | None = None,
) -> Ticket:
    """El técnico propone una solución; el ticket espera la confirmación del solicitante.

    Eventos: RESOLUTION_PROPOSED, TICKET_STATUS_CHANGED y CONFIRMATION_REQUESTED (sección 8.2).
    El técnico nunca cierra (regla 1).
    """
    text = resolution_text.strip()
    if not text:
        raise BusinessRuleViolation("Debes registrar el texto de la solución.")
    correlation_id = uuid.uuid4()

    # Si algo falla, atomic() revierte también el texto asignado aquí.
    with atomic(db):
        ticket.resolution_text = text
        validate_transition(
            ticket,
            TicketStatus.PENDIENTE_CONFIRMACION,
            technician,
            expected_version=expected_version,
        )
        audit_service.record_event(
            db,
            ticket=ticket,
            event_type=EventType.RESOLUTION_PROPOSED,
            actor=technician,
            correlation_id=correlation_id,
            details={"summary": text[:RESOLUTION_SUMMARY_LENGTH]},
        )
        # La versión ya se comprobó arriba; el flush del evento la incrementa, por eso aquí no.
        transition(
            db,
            ticket,
            TicketStatus.PENDIENTE_CONFIRMACION,
            technician,
            correlation_id=correlation_id,
        )
        requester = user_repository.get_by_id(db, ticket.requester_id)
        assert requester is not None
        notification = notification_service.enqueue(
            db,
            ticket=ticket,
            recipient=requester,
            message_type=MessageType.A3,
            correlation_id=correlation_id,
        )
        audit_service.record_event(
            db,
            ticket=ticket,
            event_type=EventType.CONFIRMATION_REQUESTED,
            actor=None,
            correlation_id=correlation_id,
            details={
                "notification_id": notification.id if notification else None,
                "channel": notification.channel.value if notification else "WEB",
                "confirmation_round": ticket.reopen_count + 1,
            },
        )
    return ticket


# --- Acciones disponibles en la interfaz ------------------------------------------------------


@dataclass(frozen=True)
class TicketActions:
    can_assign: bool
    can_start: bool
    can_resolve: bool
    can_confirm: bool
    can_validate_classification: bool


def available_actions(ticket: Ticket, user: User) -> TicketActions:
    """Qué botones mostrar; la validación real la vuelve a hacer cada operación."""
    return TicketActions(
        can_assign=user.role == Role.ADMIN
        and is_transition_allowed(ticket, TicketStatus.ASIGNADO, user),
        can_start=is_transition_allowed(ticket, TicketStatus.EN_PROCESO, user),
        can_resolve=is_transition_allowed(ticket, TicketStatus.PENDIENTE_CONFIRMACION, user),
        can_confirm=is_transition_allowed(ticket, TicketStatus.CERRADO, user),
        can_validate_classification=user.role == Role.ADMIN
        and ticket.status != TicketStatus.CERRADO,
    )
