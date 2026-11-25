"""Cómo se ve cada aviso en Telegram.

El texto base sale de las plantillas de la sección 16 y ya pasó la validación. Aquí solo le
ponemos presentación: un título con emoji, la ficha del ticket y un pie. Todo va en HTML
de Telegram y escapamos lo que viene del usuario para que nadie meta etiquetas.
"""

import html
import re
from dataclasses import dataclass

from backend.integrations.base import OutgoingMessage
from backend.models.enums import MessageType

SEPARATOR = "━━━━━━━━━━━━━━"
FOOTER = "<i>TRAZA · Soporte TI FISI</i>"

# Las plantillas dicen "Estado: X." y en Telegram el estado ya va en la ficha
STATUS_SENTENCE = re.compile(r"\s*Estado: [^.]+\.")


@dataclass(frozen=True)
class Look:
    icon: str
    title: str
    status: str | None = None
    hint: str | None = None


LOOKS: dict[MessageType, Look] = {
    MessageType.A1: Look("📥", "Solicitud registrada", "Pendiente"),
    MessageType.A2: Look("👨‍🔧", "Técnico asignado", "En atención"),
    MessageType.A3: Look(
        "🛠️",
        "Solución registrada",
        "Esperando tu confirmación",
        "👇 Cuéntanos con un botón si ya funciona.",
    ),
    MessageType.A4: Look("✅", "Solicitud cerrada", "Cerrada"),
    MessageType.A5: Look("🔄", "Solicitud reabierta", "Reabierta"),
    MessageType.A6: Look("⚠️", "Un aviso no se pudo enviar"),
    MessageType.A7: Look(
        "⏰",
        "Recordatorio",
        "Esperando tu confirmación",
        "Responde con los botones del mensaje anterior.",
    ),
    MessageType.A8: Look("🔁", "El problema continúa", "Reabierta"),
    MessageType.A9: Look("⏱️", "Plazo de atención vencido", "Sin atender"),
}


def format_message(message: OutgoingMessage) -> str:
    look = LOOKS.get(message.message_type, Look("🔔", "Aviso de TRAZA"))
    lines = [f"{look.icon} <b>{html.escape(look.title)}</b>", SEPARATOR]
    lines += _ticket_card(message, look)
    lines += ["", _body(message)]
    if look.hint:
        lines += ["", html.escape(look.hint)]
    lines += ["", FOOTER]
    return "\n".join(lines)


def _ticket_card(message: OutgoingMessage, look: Look) -> list[str]:
    card = []
    if message.ticket_code:
        card.append(f"🎫 <b>Ticket:</b> <code>{html.escape(message.ticket_code)}</code>")
    if message.ticket_title:
        card.append(f"📝 <b>Asunto:</b> {html.escape(message.ticket_title)}")
    if look.status:
        card.append(f"📌 <b>Estado:</b> {html.escape(look.status)}")
    return card


def _body(message: OutgoingMessage) -> str:
    text = html.escape(STATUS_SENTENCE.sub("", message.body).strip())
    # El código en negrita para que se ubique rápido dentro del texto
    if message.ticket_code:
        code = html.escape(message.ticket_code)
        text = text.replace(code, f"<b>{code}</b>")
    return text
