"""Esquema inicial: tablas de la sección 12, secuencia ticket_code_seq y bitácora de solo inserción.

Revision ID: 0001
Revises:
Create Date: 2026-10-20

Los valores de los enums se copian aquí a propósito (no se importan de backend.models.enums):
una migración es una foto del esquema y no debe cambiar si el código cambia después.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = ("REQUESTER", "TECHNICIAN", "ADMIN")
TICKET_STATUSES = (
    "PENDIENTE",
    "ASIGNADO",
    "EN_PROCESO",
    "PENDIENTE_CONFIRMACION",
    "CERRADO",
    "REABIERTO",
)
CATEGORIES = ("REDES", "HARDWARE", "SOFTWARE", "ACCESOS", "SEGURIDAD", "OTROS")
IMPACTS = ("INDIVIDUAL", "EQUIPO", "AREA")
URGENCIES = ("BAJA", "MEDIA", "ALTA")
PRIORITIES = ("BAJA", "MEDIA", "ALTA", "CRITICA")
CLASSIFICATION_PROVIDERS = ("openai", "rules", "mock", "manual")
ACTOR_TYPES = ("USER", "SYSTEM", "INTEGRATION")
EVENT_TYPES = (
    "TICKET_CREATED",
    "TICKET_CLASSIFIED",
    "CLASSIFICATION_FALLBACK",
    "CLASSIFICATION_VALIDATED",
    "TICKET_ASSIGNED",
    "TICKET_STATUS_CHANGED",
    "RESOLUTION_PROPOSED",
    "CONFIRMATION_REQUESTED",
    "CONFIRMATION_ACCEPTED",
    "CONFIRMATION_REJECTED",
    "TICKET_REOPENED",
    "CONFIRMATION_REMINDER",
    "ADMIN_ALERT",
    "NOTIFICATION_SENT",
    "NOTIFICATION_FAILED",
    "SLA_BREACHED",
    "DUPLICATE_ANSWER_IGNORED",
    "TICKET_CLOSED_BY_ADMIN",
)
NOTIFICATION_CHANNELS = ("WHATSAPP", "SIMULATED")
MESSAGE_TYPES = ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8")
NOTIFICATION_STATUSES = ("PENDING", "SENT", "DELIVERED", "READ", "FAILED", "RETRYING", "SIMULATED")
CONFIRMATION_ANSWERS = ("YES", "NO")
CONFIRMATION_SOURCES = ("WHATSAPP", "WEB", "SIMULATOR")
JOB_TYPES = ("CLASSIFY_TICKET", "AUTO_ASSIGN", "SEND_NOTIFICATION")
JOB_STATUSES = ("PENDING", "RUNNING", "DONE", "FAILED")


def _enum_column(name: str, values: tuple[str, ...], nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.String(max(len(v) for v in values)), nullable=nullable)


def _enum_check(name: str, values: tuple[str, ...]) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    # El nombre final lo arma la convención de nombres: ck_<tabla>_<columna>.
    return sa.CheckConstraint(f"{name} IN ({allowed})", name=name)


def _id() -> sa.Column:
    return sa.Column("id", sa.Integer(), primary_key=True)


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _tz(name: str, nullable: bool = True, now_default: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.func.now() if now_default else None,
        nullable=nullable,
    )


def _jsonb(name: str) -> sa.Column:
    return sa.Column(
        name, postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
    )


def upgrade() -> None:
    # Los nombres de restricciones sin nombre explícito salen de la convención de
    # Base.metadata (env.py la pasa como target_metadata): pk_*, fk_*, ck_*, uq_*.
    op.create_table(
        "users",
        _id(),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("phone_e164", sa.String(16), nullable=True),
        _enum_column("role", ROLES),
        sa.Column("whatsapp_opt_in", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        _created_at(),
        _enum_check("role", ROLES),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.execute("CREATE SEQUENCE ticket_code_seq START WITH 1 INCREMENT BY 1")

    op.create_table(
        "tickets",
        _id(),
        sa.Column("public_code", sa.String(20), nullable=False),
        sa.Column("requester_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location", sa.String(120), nullable=True),
        _enum_column("category", CATEGORIES, nullable=True),
        _enum_column("impact", IMPACTS, nullable=True),
        _enum_column("urgency", URGENCIES, nullable=True),
        _enum_column("priority", PRIORITIES, nullable=True),
        sa.Column("review_required", sa.Boolean(), server_default=sa.false(), nullable=False),
        _enum_column("status", TICKET_STATUSES),
        sa.Column("assigned_technician_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("resolution_text", sa.Text(), nullable=True),
        sa.Column("reopen_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        _created_at(),
        _tz("updated_at", nullable=False, now_default=True),
        _tz("first_response_at"),
        _tz("closed_at"),
        _tz("sla_breached_at"),
        _enum_check("category", CATEGORIES),
        _enum_check("impact", IMPACTS),
        _enum_check("urgency", URGENCIES),
        _enum_check("priority", PRIORITIES),
        _enum_check("status", TICKET_STATUSES),
    )
    op.create_index("ix_tickets_public_code", "tickets", ["public_code"], unique=True)
    op.create_index("ix_tickets_status", "tickets", ["status"])
    op.create_index("ix_tickets_assigned_technician_id", "tickets", ["assigned_technician_id"])
    op.create_index("ix_tickets_requester_id", "tickets", ["requester_id"])
    op.create_index("ix_tickets_created_at", "tickets", ["created_at"])

    op.create_table(
        "classifications",
        _id(),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id"), nullable=False),
        _enum_column("provider", CLASSIFICATION_PROVIDERS),
        _enum_column("category_suggested", CATEGORIES),
        _enum_column("impact_suggested", IMPACTS),
        _enum_column("urgency_suggested", URGENCIES),
        _enum_column("priority_computed", PRIORITIES),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("review_required", sa.Boolean(), nullable=False),
        sa.Column("rationale", sa.String(200), nullable=True),
        sa.Column("rules_version", sa.String(20), nullable=False),
        sa.Column("model_version", sa.String(100), nullable=True),
        sa.Column("validated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        _created_at(),
        _enum_check("provider", CLASSIFICATION_PROVIDERS),
        _enum_check("category_suggested", CATEGORIES),
        _enum_check("impact_suggested", IMPACTS),
        _enum_check("urgency_suggested", URGENCIES),
        _enum_check("priority_computed", PRIORITIES),
    )
    op.create_index("ix_classifications_ticket_id", "classifications", ["ticket_id"])

    op.create_table(
        "assignments",
        _id(),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("technician_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("assigned_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reason", sa.String(500), nullable=False),
        _tz("assigned_at", nullable=False, now_default=True),
        _tz("released_at"),
        _created_at(),
    )
    op.create_index("ix_assignments_ticket_id", "assignments", ["ticket_id"])
    op.create_index("ix_assignments_technician_id", "assignments", ["technician_id"])

    op.create_table(
        "ticket_events",
        _id(),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id"), nullable=False),
        _enum_column("event_type", EVENT_TYPES),
        _enum_column("actor_type", ACTOR_TYPES),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        _enum_column("old_state", TICKET_STATUSES, nullable=True),
        _enum_column("new_state", TICKET_STATUSES, nullable=True),
        _jsonb("safe_details_json"),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        _created_at(),
        _enum_check("event_type", EVENT_TYPES),
        _enum_check("actor_type", ACTOR_TYPES),
        _enum_check("old_state", TICKET_STATUSES),
        _enum_check("new_state", TICKET_STATUSES),
    )
    op.create_index(
        "ix_ticket_events_ticket_id_created_at", "ticket_events", ["ticket_id", "created_at"]
    )
    # Regla 3 / RN-08: la bitácora es solo de inserción, también a nivel de base de datos.
    op.execute(
        """
        CREATE FUNCTION ticket_events_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'ticket_events es solo de inserción: % no permitido', TG_OP;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER ticket_events_no_update_delete
        BEFORE UPDATE OR DELETE ON ticket_events
        FOR EACH ROW EXECUTE FUNCTION ticket_events_append_only()
        """
    )
    op.execute(
        """
        CREATE TRIGGER ticket_events_no_truncate
        BEFORE TRUNCATE ON ticket_events
        FOR EACH STATEMENT EXECUTE FUNCTION ticket_events_append_only()
        """
    )

    op.create_table(
        "notifications",
        _id(),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id"), nullable=False),
        _enum_column("channel", NOTIFICATION_CHANNELS),
        sa.Column("recipient_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        _enum_column("message_type", MESSAGE_TYPES),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("provider_message_id", sa.String(200), nullable=True),
        _enum_column("status", NOTIFICATION_STATUSES),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error_code", sa.String(50), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        _created_at(),
        _tz("sent_at"),
        _tz("delivered_at"),
        _enum_check("channel", NOTIFICATION_CHANNELS),
        _enum_check("message_type", MESSAGE_TYPES),
        _enum_check("status", NOTIFICATION_STATUSES),
        sa.UniqueConstraint("idempotency_key", name="uq_notifications_idempotency_key"),
    )
    op.create_index("ix_notifications_ticket_id", "notifications", ["ticket_id"])
    op.create_index(
        "ix_notifications_provider_message_id", "notifications", ["provider_message_id"]
    )

    op.create_table(
        "confirmations",
        _id(),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("requester_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "notification_id", sa.Integer(), sa.ForeignKey("notifications.id"), nullable=True
        ),
        _enum_column("answer", CONFIRMATION_ANSWERS),
        _enum_column("source", CONFIRMATION_SOURCES),
        sa.Column("provider_event_id", sa.String(200), nullable=True),
        sa.Column("confirmation_round", sa.Integer(), nullable=False),
        _tz("responded_at", nullable=False, now_default=True),
        _created_at(),
        _enum_check("answer", CONFIRMATION_ANSWERS),
        _enum_check("source", CONFIRMATION_SOURCES),
        sa.UniqueConstraint("provider_event_id", name="uq_confirmations_provider_event_id"),
        sa.UniqueConstraint(
            "ticket_id",
            "confirmation_round",
            name="uq_confirmations_ticket_id_confirmation_round",
        ),
    )

    op.create_table(
        "outbox_jobs",
        _id(),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id"), nullable=True),
        _enum_column("job_type", JOB_TYPES),
        _jsonb("payload_safe_json"),
        _enum_column("status", JOB_STATUSES),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _tz("next_run_at", nullable=False, now_default=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        _created_at(),
        _tz("completed_at"),
        _enum_check("job_type", JOB_TYPES),
        _enum_check("status", JOB_STATUSES),
    )
    op.create_index("ix_outbox_jobs_ticket_id", "outbox_jobs", ["ticket_id"])
    op.create_index("ix_outbox_jobs_status_next_run_at", "outbox_jobs", ["status", "next_run_at"])


def downgrade() -> None:
    op.drop_table("outbox_jobs")
    op.drop_table("confirmations")
    op.drop_table("notifications")
    op.execute("DROP TRIGGER IF EXISTS ticket_events_no_truncate ON ticket_events")
    op.execute("DROP TRIGGER IF EXISTS ticket_events_no_update_delete ON ticket_events")
    op.drop_table("ticket_events")
    op.execute("DROP FUNCTION IF EXISTS ticket_events_append_only()")
    op.drop_table("assignments")
    op.drop_table("classifications")
    op.drop_table("tickets")
    op.execute("DROP SEQUENCE IF EXISTS ticket_code_seq")
    op.drop_table("users")
