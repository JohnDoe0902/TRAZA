from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Confirmation


def add(db: Session, confirmation: Confirmation) -> Confirmation:
    db.add(confirmation)
    db.flush()
    return confirmation


def get_by_provider_event_id(db: Session, provider_event_id: str) -> Confirmation | None:
    query = select(Confirmation).where(Confirmation.provider_event_id == provider_event_id)
    return db.scalar(query)


def get_for_round(db: Session, ticket_id: int, confirmation_round: int) -> Confirmation | None:
    query = select(Confirmation).where(
        Confirmation.ticket_id == ticket_id,
        Confirmation.confirmation_round == confirmation_round,
    )
    return db.scalar(query)


def list_for_ticket(db: Session, ticket_id: int) -> Sequence[Confirmation]:
    query = select(Confirmation).where(Confirmation.ticket_id == ticket_id)
    return db.scalars(query.order_by(Confirmation.id)).all()
