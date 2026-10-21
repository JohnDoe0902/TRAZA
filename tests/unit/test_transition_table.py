"""Regla 2 / RN-06: tabla de transiciones de la sección 8.2, sin base de datos."""

import itertools

import pytest

from backend.core.errors import (
    BusinessRuleViolation,
    ConcurrencyConflict,
    InvalidTransition,
    NotAuthorized,
)
from backend.models import Ticket, User
from backend.models.enums import Role, TicketStatus
from backend.services.ticket_service import TRANSITIONS, validate_transition

S = TicketStatus
REQUESTER = User(id=1, role=Role.REQUESTER)
TECHNICIAN = User(id=2, role=Role.TECHNICIAN)
OTHER_TECHNICIAN = User(id=3, role=Role.TECHNICIAN)
ADMIN = User(id=4, role=Role.ADMIN)
SYSTEM = None


def make_ticket(status: TicketStatus, **overrides: object) -> Ticket:
    values: dict[str, object] = {
        "status": status,
        "requester_id": REQUESTER.id,
        "assigned_technician_id": TECHNICIAN.id,
        "resolution_text": "Solución aplicada",
        "review_required": False,
        "version": 3,
        "reopen_count": 0,
    }
    values.update(overrides)
    return Ticket(**values)


# Cada transición válida de la tabla 8.2 con un actor autorizado.
VALID = [
    (S.PENDIENTE, S.ASIGNADO, ADMIN, None),
    (S.PENDIENTE, S.ASIGNADO, SYSTEM, None),
    (S.ASIGNADO, S.ASIGNADO, ADMIN, "Cambio de turno"),
    (S.EN_PROCESO, S.ASIGNADO, ADMIN, "Técnico de licencia"),
    (S.ASIGNADO, S.EN_PROCESO, TECHNICIAN, None),
    (S.EN_PROCESO, S.PENDIENTE_CONFIRMACION, TECHNICIAN, None),
    (S.PENDIENTE_CONFIRMACION, S.CERRADO, REQUESTER, None),
    (S.PENDIENTE_CONFIRMACION, S.REABIERTO, REQUESTER, None),
    (S.REABIERTO, S.EN_PROCESO, TECHNICIAN, None),
    (S.REABIERTO, S.ASIGNADO, ADMIN, "Reasignación tras reapertura"),
]


@pytest.mark.parametrize(("from_status", "to_status", "actor", "reason"), VALID)
def test_transiciones_validas(
    from_status: TicketStatus, to_status: TicketStatus, actor: User | None, reason: str | None
) -> None:
    validate_transition(make_ticket(from_status), to_status, actor, reason=reason)


def test_la_tabla_tiene_exactamente_las_transiciones_de_la_especificacion() -> None:
    assert {(f, t) for f, t, _, _ in VALID} == set(TRANSITIONS)


INVALID_PAIRS = [
    pair for pair in itertools.product(TicketStatus, repeat=2) if pair not in TRANSITIONS
]


@pytest.mark.parametrize(("from_status", "to_status"), INVALID_PAIRS)
def test_toda_transicion_fuera_de_la_tabla_es_invalida(
    from_status: TicketStatus, to_status: TicketStatus
) -> None:
    with pytest.raises(InvalidTransition):
        validate_transition(make_ticket(from_status), to_status, ADMIN, reason="motivo")


def test_cp08_pendiente_a_cerrado_rechazado() -> None:
    with pytest.raises(InvalidTransition):
        validate_transition(make_ticket(S.PENDIENTE), S.CERRADO, REQUESTER)


@pytest.mark.parametrize(
    ("from_status", "to_status", "actor"),
    [
        (S.PENDIENTE_CONFIRMACION, S.CERRADO, TECHNICIAN),  # regla 1: el técnico no cierra
        (S.PENDIENTE_CONFIRMACION, S.CERRADO, ADMIN),  # el admin no confirma por el solicitante
        (S.PENDIENTE_CONFIRMACION, S.CERRADO, SYSTEM),  # el silencio nunca cierra
        (S.ASIGNADO, S.EN_PROCESO, OTHER_TECHNICIAN),  # técnico no asignado
        (S.ASIGNADO, S.EN_PROCESO, ADMIN),
        (S.PENDIENTE, S.ASIGNADO, TECHNICIAN),
        (S.PENDIENTE, S.ASIGNADO, REQUESTER),
        (S.ASIGNADO, S.ASIGNADO, SYSTEM),  # la reasignación es solo del admin
    ],
)
def test_actor_no_autorizado(
    from_status: TicketStatus, to_status: TicketStatus, actor: User | None
) -> None:
    with pytest.raises(NotAuthorized):
        validate_transition(make_ticket(from_status), to_status, actor, reason="motivo")


def test_otro_solicitante_no_puede_confirmar() -> None:
    with pytest.raises(NotAuthorized):
        validate_transition(
            make_ticket(S.PENDIENTE_CONFIRMACION), S.CERRADO, User(id=99, role=Role.REQUESTER)
        )


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [(S.ASIGNADO, S.ASIGNADO), (S.EN_PROCESO, S.ASIGNADO), (S.REABIERTO, S.ASIGNADO)],
)
def test_reasignacion_exige_motivo(from_status: TicketStatus, to_status: TicketStatus) -> None:
    with pytest.raises(BusinessRuleViolation):
        validate_transition(make_ticket(from_status), to_status, ADMIN, reason="  ")


def test_version_desactualizada_es_conflicto() -> None:
    with pytest.raises(ConcurrencyConflict):
        validate_transition(make_ticket(S.ASIGNADO), S.EN_PROCESO, TECHNICIAN, expected_version=2)


def test_asignacion_automatica_bloqueada_si_requiere_revision() -> None:
    ticket = make_ticket(S.PENDIENTE, review_required=True, assigned_technician_id=None)
    with pytest.raises(BusinessRuleViolation):
        validate_transition(ticket, S.ASIGNADO, SYSTEM)
    validate_transition(ticket, S.ASIGNADO, ADMIN)  # el admin sí puede asignar a mano


def test_proponer_solucion_exige_texto() -> None:
    with pytest.raises(BusinessRuleViolation):
        validate_transition(
            make_ticket(S.EN_PROCESO, resolution_text=None), S.PENDIENTE_CONFIRMACION, TECHNICIAN
        )
