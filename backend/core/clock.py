"""Hora actual en UTC (las fechas se guardan en UTC y se muestran en America/Lima)."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)
