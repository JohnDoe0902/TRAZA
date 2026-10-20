"""Plantillas de mensajes por defecto (sección 16)."""

import pytest

from backend.models.enums import MessageType
from backend.services.message_service import MessageContext, compose, first_name


@pytest.mark.parametrize("message_type", list(MessageType))
def test_toda_plantilla_incluye_el_codigo(message_type: MessageType) -> None:
    text = compose(message_type, MessageContext(code="TRZ-0042", first_name="Elena"))
    assert "TRZ-0042" in text
    assert "{" not in text  # sin variables sin reemplazar
    assert len(text) <= 500


def test_a1_saluda_por_nombre_de_pila() -> None:
    text = compose(MessageType.A1, MessageContext(code="TRZ-0001", first_name="Elena"))
    assert text.startswith("Hola, Elena. TRAZA registró tu solicitud TRZ-0001.")


def test_a1_sin_nombre() -> None:
    text = compose(MessageType.A1, MessageContext(code="TRZ-0001"))
    assert text.startswith("Hola. TRAZA registró")


def test_a6_incluye_el_intento() -> None:
    text = compose(MessageType.A6, MessageContext(code="TRZ-0001", attempt=3))
    assert "Intento 3." in text


def test_nombre_de_pila() -> None:
    assert first_name("Elena Quispe Rojas") == "Elena"
    assert first_name("") == ""
