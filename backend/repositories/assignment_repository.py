from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from backend.models import Assignment, Ticket, User
from backend.models.enums import Role, TicketStatus

# Estados en los que un ticket cuenta como carga abierta de su técnico (RN-07).
OPEN_STATUSES = (
    TicketStatus.ASIGNADO,
    TicketStatus.EN_PROCESO,
    TicketStatus.PENDIENTE_CONFIRMACION,
    TicketStatus.REABIERTO,
)


def add(db: Session, assignment: Assignment) -> Assignment:
    db.add(assignment)
    db.flush()
    return assignment


def current_for_ticket(db: Session, ticket_id: int) -> Assignment | None:
    query = select(Assignment).where(
        Assignment.ticket_id == ticket_id, Assignment.released_at.is_(None)
    )
    return db.scalars(query.order_by(Assignment.id.desc())).first()


def least_loaded_active_technician(db: Session) -> User | None:
    """Técnico activo con menos tickets abiertos; empate → menor id (RN-07)."""
    query = (
        select(User)
        .outerjoin(
            Ticket,
            and_(Ticket.assigned_technician_id == User.id, Ticket.status.in_(OPEN_STATUSES)),
        )
        .where(User.role == Role.TECHNICIAN, User.is_active.is_(True))
        .group_by(User.id)
        .order_by(func.count(Ticket.id), User.id)
        .limit(1)
    )
    return db.scalars(query).first()
