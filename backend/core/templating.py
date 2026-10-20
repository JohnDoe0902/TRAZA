"""Entorno de Jinja2: plantillas, filtros de fechas y etiquetas en español (RNF-07)."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

from backend.core.config import get_settings
from backend.models import TicketEvent, User
from backend.models.enums import (
    Category,
    EventType,
    Impact,
    MessageType,
    NotificationStatus,
    Priority,
    Role,
    TicketStatus,
    Urgency,
)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

STATUS_LABELS = {
    TicketStatus.PENDIENTE: "Pendiente",
    TicketStatus.ASIGNADO: "Asignado",
    TicketStatus.EN_PROCESO: "En proceso",
    TicketStatus.PENDIENTE_CONFIRMACION: "Pendiente de confirmación",
    TicketStatus.CERRADO: "Cerrado",
    TicketStatus.REABIERTO: "Reabierto",
}
STATUS_BADGES = {
    TicketStatus.PENDIENTE: "text-bg-secondary",
    TicketStatus.ASIGNADO: "text-bg-info",
    TicketStatus.EN_PROCESO: "text-bg-primary",
    TicketStatus.PENDIENTE_CONFIRMACION: "text-bg-warning",
    TicketStatus.CERRADO: "text-bg-success",
    TicketStatus.REABIERTO: "text-bg-danger",
}
PRIORITY_LABELS = {
    Priority.BAJA: "Baja",
    Priority.MEDIA: "Media",
    Priority.ALTA: "Alta",
    Priority.CRITICA: "Crítica",
}
PRIORITY_BADGES = {
    Priority.BAJA: "text-bg-light border",
    Priority.MEDIA: "text-bg-info",
    Priority.ALTA: "text-bg-warning",
    Priority.CRITICA: "text-bg-danger",
}
ROLE_LABELS = {
    Role.REQUESTER: "Solicitante",
    Role.TECHNICIAN: "Técnico",
    Role.ADMIN: "Administrador",
}
CATEGORY_LABELS = {
    Category.REDES: "Redes",
    Category.HARDWARE: "Hardware",
    Category.SOFTWARE: "Software",
    Category.ACCESOS: "Accesos",
    Category.SEGURIDAD: "Seguridad",
    Category.OTROS: "Otros",
}
IMPACT_LABELS = {
    Impact.INDIVIDUAL: "Individual",
    Impact.EQUIPO: "Equipo",
    Impact.AREA: "Área completa",
}
URGENCY_LABELS = {Urgency.BAJA: "Baja", Urgency.MEDIA: "Media", Urgency.ALTA: "Alta"}
EVENT_LABELS = {
    EventType.TICKET_CREATED: "Solicitud registrada",
    EventType.TICKET_CLASSIFIED: "Clasificación automática",
    EventType.CLASSIFICATION_FALLBACK: "Clasificación por reglas (respaldo)",
    EventType.CLASSIFICATION_VALIDATED: "Clasificación validada",
    EventType.TICKET_ASSIGNED: "Técnico asignado",
    EventType.TICKET_STATUS_CHANGED: "Cambio de estado",
    EventType.RESOLUTION_PROPOSED: "Solución propuesta",
    EventType.CONFIRMATION_REQUESTED: "Confirmación solicitada",
    EventType.CONFIRMATION_ACCEPTED: "El solicitante confirmó la solución",
    EventType.CONFIRMATION_REJECTED: "El solicitante indicó que el problema continúa",
    EventType.TICKET_REOPENED: "Ticket reabierto",
    EventType.CONFIRMATION_REMINDER: "Recordatorio de confirmación",
    EventType.ADMIN_ALERT: "Alerta al administrador",
    EventType.NOTIFICATION_SENT: "Mensaje enviado",
    EventType.NOTIFICATION_FAILED: "Falla de envío de mensaje",
    EventType.SLA_BREACHED: "Plazo vencido",
    EventType.DUPLICATE_ANSWER_IGNORED: "Respuesta repetida o tardía ignorada",
    EventType.TICKET_CLOSED_BY_ADMIN: "Cierre excepcional del administrador",
}
MESSAGE_TYPE_LABELS = {
    MessageType.A1: "Ticket recibido",
    MessageType.A2: "Técnico asignado",
    MessageType.A3: "Pedido de confirmación",
    MessageType.A4: "Cierre confirmado",
    MessageType.A5: "Reapertura",
    MessageType.A6: "Falla de envío",
    MessageType.A7: "Recordatorio",
    MessageType.A8: "Aviso al técnico",
}
NOTIFICATION_STATUS_LABELS = {
    NotificationStatus.PENDING: "En cola",
    NotificationStatus.SENT: "Enviado",
    NotificationStatus.DELIVERED: "Entregado",
    NotificationStatus.READ: "Leído",
    NotificationStatus.FAILED: "Falló",
    NotificationStatus.RETRYING: "Reintentando",
    NotificationStatus.SIMULATED: "Simulado",
}
SOURCE_LABELS = {"WEB": "web", "SIMULATOR": "simulador", "WHATSAPP": "WhatsApp"}
ALERT_REASONS = {
    "sin_tecnicos_activos": "no hay técnicos activos para asignar",
    "job_failed": "un trabajo automático agotó sus reintentos",
}
FALLBACK_REASONS = {
    "timeout": "el proveedor no respondió a tiempo",
    "invalid_output": "la respuesta del proveedor no era válida",
    "provider_error": "el proveedor devolvió un error",
}


def local_datetime(value: datetime | None, fmt: str = "%d/%m/%Y %H:%M") -> str:
    """Fecha guardada en UTC mostrada en la zona horaria configurada (America/Lima)."""
    if value is None:
        return "—"
    return value.astimezone(ZoneInfo(get_settings().timezone)).strftime(fmt)


def describe_event(event: TicketEvent, users: dict[int, User]) -> str:
    """Detalle legible de un evento para la línea de tiempo."""
    details = event.safe_details_json or {}

    def name(user_id: object) -> str:
        user = users.get(user_id) if isinstance(user_id, int) else None
        return user.full_name if user else "—"

    match event.event_type:
        case EventType.TICKET_STATUS_CHANGED | EventType.TICKET_REOPENED:
            text = f"{STATUS_LABELS.get(event.old_state, '—')} → {STATUS_LABELS[event.new_state]}"
            if details.get("reason"):
                text += f". Motivo: {details['reason']}"
            return text
        case EventType.TICKET_CLASSIFIED:
            priority = PRIORITY_LABELS.get(Priority(details["priority"]), details["priority"])
            text = (
                f"{CATEGORY_LABELS.get(Category(details['category']))} · "
                f"impacto {IMPACT_LABELS.get(Impact(details['impact'])).lower()} · "
                f"urgencia {URGENCY_LABELS.get(Urgency(details['urgency'])).lower()} → "
                f"prioridad {priority.lower()} ({details['provider']})"
            )
            if details.get("review_required"):
                text += ". Requiere revisión humana"
            return text
        case EventType.CLASSIFICATION_FALLBACK:
            return FALLBACK_REASONS.get(details.get("reason"), str(details.get("reason")))
        case EventType.TICKET_ASSIGNED:
            return f"{name(details.get('technician_id'))}. Motivo: {details.get('reason', '—')}"
        case EventType.RESOLUTION_PROPOSED:
            return str(details.get("summary", ""))
        case EventType.CONFIRMATION_ACCEPTED | EventType.CONFIRMATION_REJECTED:
            return f"Respuesta por {SOURCE_LABELS.get(details.get('source'), '—')}"
        case EventType.DUPLICATE_ANSWER_IGNORED:
            return f"Respuesta por {SOURCE_LABELS.get(details.get('source'), '—')} sin efecto"
        case EventType.NOTIFICATION_SENT:
            message_type = MessageType(details["message_type"])
            return f"{message_type.value} · {MESSAGE_TYPE_LABELS[message_type]}"
        case EventType.NOTIFICATION_FAILED:
            return f"Intento {details.get('attempt')}: {details.get('error_code')}"
        case EventType.ADMIN_ALERT:
            return ALERT_REASONS.get(details.get("reason"), str(details.get("reason")))
        case _:
            return ""


def _label(labels: dict) -> object:
    def apply(value: object) -> str:
        if value is None:
            return "—"
        return labels.get(value, str(value))

    return apply


templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters["local_datetime"] = local_datetime
templates.env.filters["status_label"] = _label(STATUS_LABELS)
templates.env.filters["priority_label"] = _label(PRIORITY_LABELS)
templates.env.filters["role_label"] = _label(ROLE_LABELS)
templates.env.filters["category_label"] = _label(CATEGORY_LABELS)
templates.env.filters["impact_label"] = _label(IMPACT_LABELS)
templates.env.filters["urgency_label"] = _label(URGENCY_LABELS)
templates.env.globals["STATUS_BADGES"] = STATUS_BADGES
templates.env.globals["PRIORITY_BADGES"] = PRIORITY_BADGES
templates.env.globals["STATUS_LABELS"] = STATUS_LABELS
templates.env.filters["event_label"] = _label(EVENT_LABELS)
templates.env.filters["message_type_label"] = _label(MESSAGE_TYPE_LABELS)
templates.env.filters["notification_status_label"] = _label(NOTIFICATION_STATUS_LABELS)
templates.env.globals["Role"] = Role
templates.env.globals["PRIORITY_LABELS"] = PRIORITY_LABELS
templates.env.globals["describe_event"] = describe_event
templates.env.globals["SIMULATOR_ENABLED"] = get_settings().is_development
