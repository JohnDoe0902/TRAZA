"""Sección 13.2: validación de un mensaje antes de enviarlo."""

import pytest

from backend.integrations.base import ComposeRequest
from backend.models.enums import MessageType, TicketStatus
from backend.services.message_service import (
    MessageContext,
    TemplateComposer,
    compose,
    compose_request,
    validate_message,
)

CODE = "TRZ-0042"
S = TicketStatus

# Estado en el que se envía normalmente cada mensaje.
NATURAL_STATUS = {
    MessageType.A1: S.PENDIENTE,
    MessageType.A2: S.ASIGNADO,
    MessageType.A3: S.PENDIENTE_CONFIRMACION,
    MessageType.A4: S.CERRADO,
    MessageType.A5: S.REABIERTO,
    MessageType.A6: S.ASIGNADO,
    MessageType.A7: S.PENDIENTE_CONFIRMACION,
    MessageType.A8: S.REABIERTO,
}


@pytest.mark.parametrize("message_type", list(MessageType))
def test_toda_plantilla_pasa_la_validacion(message_type: MessageType) -> None:
    text = compose(message_type, MessageContext(code=CODE, first_name="Elena"))
    assert validate_message(text, CODE, NATURAL_STATUS[message_type]) is None


@pytest.mark.parametrize(
    ("text", "status", "reason"),
    [
        ("", S.ASIGNADO, "empty"),
        (f"{CODE} " + "x" * 500, S.ASIGNADO, "too_long"),
        ("Tu solicitud ya fue asignada.", S.ASIGNADO, "missing_code"),
        (f"Tu caso {CODE} ya está resuelto.", S.PENDIENTE_CONFIRMACION, "claims_closed"),
        (f"Tu solicitud {CODE} quedó cerrada.", S.EN_PROCESO, "claims_closed"),
        (f"Tu caso {CODE} quedó RESUELTO", S.ASIGNADO, "claims_closed"),
        (f"Revisa https://traza.example para {CODE}", S.ASIGNADO, "contains_url"),
        (f"Entra a www.fisi.edu para {CODE}", S.ASIGNADO, "contains_url"),
        (f"Visita traza.pe para {CODE}", S.ASIGNADO, "contains_url"),
        (f"Escribe a soporte@fisi.edu.pe por {CODE}", S.ASIGNADO, "contains_email"),
        (f"Llama al 987654321 por {CODE}", S.ASIGNADO, "contains_phone"),
        (f"Llama al +51 900 000 001 por {CODE}", S.ASIGNADO, "contains_phone"),
    ],
)
def test_mensajes_rechazados(text: str, status: TicketStatus, reason: str) -> None:
    assert validate_message(text, CODE, status) == reason


@pytest.mark.parametrize(
    ("text", "status"),
    [
        (f"Gracias por confirmar. Tu solicitud {CODE} quedó cerrada.", S.CERRADO),
        (f"La solicitud {CODE} fue reabierta porque el problema continúa.", S.REABIERTO),
        (f"¿Se resolvió el problema de {CODE}?", S.PENDIENTE_CONFIRMACION),
        (f"Tu solicitud {CODE} fue asignada. Laboratorio 3, aula 105.", S.ASIGNADO),
    ],
)
def test_mensajes_aceptados(text: str, status: TicketStatus) -> None:
    assert validate_message(text, CODE, status) is None


def test_el_contexto_para_gpt_no_incluye_el_nombre() -> None:
    request = compose_request(MessageType.A1, CODE, S.PENDIENTE)

    assert isinstance(request, ComposeRequest)
    assert request.base_message.startswith("Hola. TRAZA registró tu solicitud TRZ-0042.")
    assert request.status_label == "Pendiente"
    assert request.purpose


def test_el_redactor_por_defecto_usa_la_plantilla() -> None:
    request = compose_request(MessageType.A3, CODE, S.PENDIENTE_CONFIRMACION)
    assert TemplateComposer().compose(request) == request.base_message
