from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Classification


def add(db: Session, classification: Classification) -> Classification:
    db.add(classification)
    db.flush()
    return classification


def latest_for_ticket(db: Session, ticket_id: int) -> Classification | None:
    query = select(Classification).where(Classification.ticket_id == ticket_id)
    return db.scalars(query.order_by(Classification.id.desc())).first()
