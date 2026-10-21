"""Unidad de trabajo: todo o nada en una transacción."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.core.errors import ConcurrencyConflict


@contextmanager
def atomic(db: Session) -> Iterator[None]:
    """Confirma al salir sin errores; ante cualquier excepción revierte todo.

    Un conflicto del bloqueo optimista (`tickets.version`) se traduce a ConcurrencyConflict (409).
    """
    try:
        yield
        db.commit()
    except StaleDataError as exc:
        db.rollback()
        raise ConcurrencyConflict() from exc
    except BaseException:
        db.rollback()
        raise
