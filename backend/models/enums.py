"""Enums de dominio. Se guardan como texto con CHECK en la base (sección 12)."""

from enum import StrEnum


class Role(StrEnum):
    REQUESTER = "REQUESTER"
    TECHNICIAN = "TECHNICIAN"
    ADMIN = "ADMIN"


class TicketStatus(StrEnum):
    PENDIENTE = "PENDIENTE"
    ASIGNADO = "ASIGNADO"
    EN_PROCESO = "EN_PROCESO"
    PENDIENTE_CONFIRMACION = "PENDIENTE_CONFIRMACION"
    CERRADO = "CERRADO"
    REABIERTO = "REABIERTO"


class Category(StrEnum):
    REDES = "REDES"
    HARDWARE = "HARDWARE"
    SOFTWARE = "SOFTWARE"
    ACCESOS = "ACCESOS"
    SEGURIDAD = "SEGURIDAD"
    OTROS = "OTROS"


class Impact(StrEnum):
    INDIVIDUAL = "INDIVIDUAL"
    EQUIPO = "EQUIPO"
    AREA = "AREA"


class Urgency(StrEnum):
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"


class Priority(StrEnum):
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"
    CRITICA = "CRITICA"


class ClassificationProvider(StrEnum):
    OPENAI = "openai"
    RULES = "rules"
    MOCK = "mock"
    MANUAL = "manual"


class ActorType(StrEnum):
    USER = "USER"
    SYSTEM = "SYSTEM"
    INTEGRATION = "INTEGRATION"


class EventType(StrEnum):
    TICKET_CREATED = "TICKET_CREATED"
    TICKET_CLASSIFIED = "TICKET_CLASSIFIED"
    CLASSIFICATION_FALLBACK = "CLASSIFICATION_FALLBACK"
    CLASSIFICATION_VALIDATED = "CLASSIFICATION_VALIDATED"
    TICKET_ASSIGNED = "TICKET_ASSIGNED"
    TICKET_STATUS_CHANGED = "TICKET_STATUS_CHANGED"
    RESOLUTION_PROPOSED = "RESOLUTION_PROPOSED"
    CONFIRMATION_REQUESTED = "CONFIRMATION_REQUESTED"
    CONFIRMATION_ACCEPTED = "CONFIRMATION_ACCEPTED"
    CONFIRMATION_REJECTED = "CONFIRMATION_REJECTED"
    TICKET_REOPENED = "TICKET_REOPENED"
    CONFIRMATION_REMINDER = "CONFIRMATION_REMINDER"
    ADMIN_ALERT = "ADMIN_ALERT"
    NOTIFICATION_SENT = "NOTIFICATION_SENT"
    NOTIFICATION_FAILED = "NOTIFICATION_FAILED"
    SLA_BREACHED = "SLA_BREACHED"
    DUPLICATE_ANSWER_IGNORED = "DUPLICATE_ANSWER_IGNORED"
    TICKET_CLOSED_BY_ADMIN = "TICKET_CLOSED_BY_ADMIN"


class NotificationChannel(StrEnum):
    WHATSAPP = "WHATSAPP"
    SIMULATED = "SIMULATED"


class MessageType(StrEnum):
    A1 = "A1"  # Ticket recibido
    A2 = "A2"  # Técnico asignado
    A3 = "A3"  # Pedido de confirmación
    A4 = "A4"  # Cierre confirmado
    A5 = "A5"  # Reapertura
    A6 = "A6"  # Falla de envío (solo admin)
    A7 = "A7"  # Recordatorio
    A8 = "A8"  # Aviso al técnico


class NotificationStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    READ = "READ"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    SIMULATED = "SIMULATED"


class ConfirmationAnswer(StrEnum):
    YES = "YES"
    NO = "NO"


class ConfirmationSource(StrEnum):
    WHATSAPP = "WHATSAPP"
    WEB = "WEB"
    SIMULATOR = "SIMULATOR"


class JobType(StrEnum):
    CLASSIFY_TICKET = "CLASSIFY_TICKET"
    AUTO_ASSIGN = "AUTO_ASSIGN"
    SEND_NOTIFICATION = "SEND_NOTIFICATION"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
