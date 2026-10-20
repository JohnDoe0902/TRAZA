"""Base declarativa común a todos los modelos."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class CommonColumnsMixin:
    """`id` entero autoincremental y `created_at` en UTC, comunes a todas las tablas."""

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def str_enum(enum_cls: type[StrEnum], column: str) -> Enum:
    """Enum guardado como VARCHAR con CHECK (no enum nativo de PostgreSQL).

    `column` da nombre al CHECK (`ck_<tabla>_<columna>`), que debe ser único en la tabla.
    """
    return Enum(
        enum_cls,
        name=column,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda members: [m.value for m in members],
        length=max(len(m.value) for m in enum_cls),
    )


def tz_datetime() -> DateTime:
    return DateTime(timezone=True)
