"""Cómo se ve cada aviso en Telegram."""

import pytest

from backend.integrations.base import OutgoingMessage
from backend.integrations.telegram_format import LOOKS, format_message
from backend.models.enums import MessageType
from backend.services.message_service import MessageContext, compose


def outgoing(
    message_type: MessageType, title: str = "Laboratorio 3 sin internet"
) -> OutgoingMessage:
    body = compose(message_type, MessageContext(code="TRZ-0007", first_name="Elena"))
    return OutgoingMessage(
        notification_id=1,
        message_type=message_type,
        body=body,
        phone_e164=None,
        telegram_chat_id=55,
        ticket_code="TRZ-0007",
        ticket_title=title,
    )


def test_el_aviso_trae_titulo_ficha_y_pie() -> None:
    text = format_message(outgoing(MessageType.A1))

    lines = text.splitlines()
    assert lines[0] == "📥 <b>Solicitud registrada</b>"
    assert "🎫 <b>Ticket:</b> <code>TRZ-0007</code>" in lines
    assert "📝 <b>Asunto:</b> Laboratorio 3 sin internet" in lines
    assert "📌 <b>Estado:</b> Pendiente" in lines
    assert lines[-1] == "<i>TRAZA · Soporte TI FISI</i>"


def test_el_estado_no_se_repite_en_el_texto() -> None:
    text = format_message(outgoing(MessageType.A1))

    # La plantilla dice "Estado: Pendiente." pero ya va en la ficha
    assert text.count("Estado") == 1
    assert "<b>TRZ-0007</b>" in text


def test_la_pregunta_invita_a_usar_los_botones() -> None:
    assert "👇" in format_message(outgoing(MessageType.A3))


def test_lo_que_escribe_el_usuario_se_escapa() -> None:
    text = format_message(outgoing(MessageType.A1, title="<b>Impresora</b> & tóner"))

    assert "&lt;b&gt;Impresora&lt;/b&gt; &amp; tóner" in text
    assert "<b>Impresora</b>" not in text


@pytest.mark.parametrize("message_type", list(MessageType))
def test_todos_los_avisos_tienen_diseno_y_caben(message_type: MessageType) -> None:
    text = format_message(outgoing(message_type, title="x" * 120))

    assert message_type in LOOKS
    assert len(text) < 4096  # límite de Telegram por mensaje


def test_el_diseno_no_toca_el_texto_guardado() -> None:
    # El diseño es solo de Telegram. La plantilla guardada sigue igual para el simulador
    message = outgoing(MessageType.A4)
    original = message.body

    format_message(message)

    assert message.body == original
