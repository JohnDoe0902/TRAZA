"""Entorno de Jinja2: plantillas, filtros de fechas y etiquetas en español (RNF-07)."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

from backend.core.config import get_settings
from backend.models.enums import Category, Impact, Priority, Role, TicketStatus, Urgency

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


def local_datetime(value: datetime | None, fmt: str = "%d/%m/%Y %H:%M") -> str:
    """Fecha guardada en UTC mostrada en la zona horaria configurada (America/Lima)."""
    if value is None:
        return "—"
    return value.astimezone(ZoneInfo(get_settings().timezone)).strftime(fmt)


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
templates.env.globals["Role"] = Role
