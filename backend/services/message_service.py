"""Redacción de mensajes (secciones 13.2 y 16).

- Las plantillas de la sección 16 son la redacción por defecto y el respaldo (regla 6).
- Un texto redactado por GPT solo se usa si pasa `validate_message`; si no, va la plantilla.
- A GPT nunca se le envían nombres (RN-14): recibe el mensaje base sin el nombre de pila.
"""

import re
import unicodedata
from dataclasses import dataclass

from backend.integrations.base import ComposeRequest
from backend.models.enums import MessageType, TicketStatus

TEMPLATES: dict[MessageType, str] = {
    MessageType.A1: (
        "Hola, {nombre}. TRAZA registró tu solicitud {codigo}. Estado: Pendiente. "
        "Te avisaremos cuando sea asignada a un técnico."
    ),
    MessageType.A2: (
        "Tu solicitud {codigo} fue asignada al equipo de soporte. Estado: En atención."
    ),
    MessageType.A3: (
        "El equipo técnico registró una solución para {codigo}. ¿El problema quedó solucionado?"
    ),
    MessageType.A4: (
        "Gracias por confirmar. Tu solicitud {codigo} quedó cerrada. "
        "TRAZA conserva el historial de la atención."
    ),
    MessageType.A5: (
        "Recibimos tu respuesta. La solicitud {codigo} fue reabierta porque el problema "
        "continúa. Avisamos al técnico responsable."
    ),
    MessageType.A6: (
        "No se pudo enviar el mensaje del ticket {codigo}. Intento {n}. "
        "Se programó un nuevo intento o requiere revisión."
    ),
    MessageType.A7: "Recordatorio: aún no nos confirmas si se resolvió {codigo}.",
    MessageType.A8: (
        "El solicitante indicó que el problema de {codigo} continúa. El ticket volvió a tu bandeja."
    ),
}


@dataclass(frozen=True)
class MessageContext:
    """Solo datos verificados: código, nombre de pila y número de intento."""

    code: str
    first_name: str = ""
    attempt: int | None = None


def first_name(full_name: str) -> str:
    return full_name.split()[0] if full_name.strip() else ""


def compose(message_type: MessageType, context: MessageContext) -> str:
    text = TEMPLATES[message_type].format(
        codigo=context.code, nombre=context.first_name, n=context.attempt or 1
    )
    # Sin nombre de pila, "Hola, ." queda feo: se simplifica a "Hola.".
    return text.replace("Hola, . ", "Hola. ")


# --- Contexto para un redactor externo -------------------------------------------------------

PURPOSES: dict[MessageType, str] = {
    MessageType.A1: "Confirmar al solicitante que su solicitud quedó registrada.",
    MessageType.A2: "Avisar al solicitante que su solicitud fue asignada al equipo de soporte.",
    MessageType.A3: "Preguntar al solicitante si el problema quedó solucionado (Sí o No).",
    MessageType.A4: "Agradecer al solicitante y confirmar el cierre de su solicitud.",
    MessageType.A5: "Avisar al solicitante que su solicitud se reabrió porque el problema sigue.",
    MessageType.A6: "Avisar al administrador que un mensaje no se pudo enviar.",
    MessageType.A7: "Recordar al solicitante que confirme si se resolvió su solicitud.",
    MessageType.A8: "Avisar al técnico que el solicitante indicó que el problema continúa.",
}

STATUS_LABELS_FOR_MESSAGES: dict[TicketStatus, str] = {
    TicketStatus.PENDIENTE: "Pendiente",
    TicketStatus.ASIGNADO: "Asignado",
    TicketStatus.EN_PROCESO: "En proceso",
    TicketStatus.PENDIENTE_CONFIRMACION: "Pendiente de confirmación",
    TicketStatus.CERRADO: "Cerrado",
    TicketStatus.REABIERTO: "Reabierto",
}


def compose_request(
    message_type: MessageType, code: str, status: TicketStatus, attempt: int | None = None
) -> ComposeRequest:
    """Lo que se envía a un redactor externo: sin nombre de pila ni datos de contacto."""
    return ComposeRequest(
        message_type=message_type,
        purpose=PURPOSES[message_type],
        ticket_code=code,
        status_label=STATUS_LABELS_FOR_MESSAGES[status],
        base_message=compose(message_type, MessageContext(code=code, attempt=attempt)),
    )


class TemplateComposer:
    """Redactor por defecto: las plantillas fijas de la sección 16."""

    name = "templates"

    def compose(self, request: ComposeRequest) -> str:
        return request.base_message


# --- Validación antes de enviar (sección 13.2) -----------------------------------------------

MAX_MESSAGE_LENGTH = 500
URL_PATTERN = re.compile(
    r"(https?://|www\.|\b[a-z0-9-]+\.(com|net|org|pe|edu|gob|io|ly|app)\b)", re.IGNORECASE
)
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
PHONE_PATTERN = re.compile(r"\+?\d(?:[\s-]?\d){6,}")
CLOSED_WORDS = re.compile(r"\b(cerrad[oa]s?|resuelt[oa]s?)\b")


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def validate_message(text: str, code: str, status: TicketStatus) -> str | None:
    """Devuelve el motivo del rechazo o None si el mensaje se puede enviar."""
    if not text.strip():
        return "empty"
    if len(text) > MAX_MESSAGE_LENGTH:
        return "too_long"
    if code not in text:
        return "missing_code"
    if status != TicketStatus.CERRADO and CLOSED_WORDS.search(_normalize(text)):
        return "claims_closed"
    # Primero el correo: su dominio ("fisi.edu.pe") también parecería una URL.
    if EMAIL_PATTERN.search(text):
        return "contains_email"
    if URL_PATTERN.search(text):
        return "contains_url"
    if PHONE_PATTERN.search(text):
        return "contains_phone"
    return None
