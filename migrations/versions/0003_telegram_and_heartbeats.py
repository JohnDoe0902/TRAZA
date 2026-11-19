"""Telegram, latido del worker y plantilla A9 (frente B, decisiones D-41 y D-46).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-17

- users: chat de Telegram vinculado y el token de un solo uso para vincularlo.
- worker_heartbeats: cada worker deja aquí su última señal de vida para /health.
- notifications.channel y confirmations.source aceptan TELEGRAM.
- notifications.message_type acepta A9 (recordatorio al técnico por plazo vencido).

Igual que en la 0001 los valores de los enums se copian aquí a propósito.
Ojo con el downgrade: falla si ya hay filas con TELEGRAM o A9. Es lo esperado
porque borrarlas sería perder historial.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_CHANNELS = ("WHATSAPP", "SIMULATED")
NEW_CHANNELS = ("WHATSAPP", "SIMULATED", "TELEGRAM")
OLD_SOURCES = ("WHATSAPP", "WEB", "SIMULATOR")
NEW_SOURCES = ("WHATSAPP", "WEB", "SIMULATOR", "TELEGRAM")
OLD_MESSAGE_TYPES = ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8")
NEW_MESSAGE_TYPES = (*OLD_MESSAGE_TYPES, "A9")

# (tabla, columna) de cada CHECK que cambia. El nombre sale de la convención ck_<tabla>_<col>
ENUM_CHECKS = {
    ("notifications", "channel"): (OLD_CHANNELS, NEW_CHANNELS),
    ("confirmations", "source"): (OLD_SOURCES, NEW_SOURCES),
    ("notifications", "message_type"): (OLD_MESSAGE_TYPES, NEW_MESSAGE_TYPES),
}


def _replace_check(table: str, column: str, values: tuple[str, ...]) -> None:
    # op.f() marca el nombre como final y así la convención no le pone el prefijo dos veces
    name = op.f(f"ck_{table}_{column}")
    allowed = ", ".join(f"'{v}'" for v in values)
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, f"{column} IN ({allowed})")


def upgrade() -> None:
    # El chat_id de Telegram puede pasar de 32 bits así que va como BIGINT
    op.add_column("users", sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("telegram_link_token", sa.String(64), nullable=True))
    op.add_column(
        "users",
        sa.Column("telegram_link_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(op.f("uq_users_telegram_chat_id"), "users", ["telegram_chat_id"])
    op.create_unique_constraint(
        op.f("uq_users_telegram_link_token"), "users", ["telegram_link_token"]
    )

    # Una fila por worker. Se actualiza en cada ciclo así que no guarda historial
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(100), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )

    for (table, column), (_, new_values) in ENUM_CHECKS.items():
        _replace_check(table, column, new_values)


def downgrade() -> None:
    for (table, column), (old_values, _) in ENUM_CHECKS.items():
        _replace_check(table, column, old_values)

    op.drop_table("worker_heartbeats")
    op.drop_constraint(op.f("uq_users_telegram_link_token"), "users", type_="unique")
    op.drop_constraint(op.f("uq_users_telegram_chat_id"), "users", type_="unique")
    op.drop_column("users", "telegram_link_expires_at")
    op.drop_column("users", "telegram_link_token")
    op.drop_column("users", "telegram_chat_id")
