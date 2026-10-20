from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import OutboxJob


def add(db: Session, job: OutboxJob) -> OutboxJob:
    db.add(job)
    db.flush()
    return job


def list_for_ticket(db: Session, ticket_id: int) -> Sequence[OutboxJob]:
    query = select(OutboxJob).where(OutboxJob.ticket_id == ticket_id).order_by(OutboxJob.id)
    return db.scalars(query).all()
