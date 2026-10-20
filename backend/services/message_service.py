"""Redacción de mensajes con las plantillas por defecto (sección 16).

La redacción con GPT y la validación de la sección 13.2 llegan en la Fase 3.
"""

from dataclasses import dataclass

from backend.models.enums import MessageType

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
