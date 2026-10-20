from collections.abc import Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models import User
from backend.models.enums import Role


def get_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.lower()))


def get_many(db: Session, user_ids: Iterable[int]) -> dict[int, User]:
    ids = set(user_ids)
    if not ids:
        return {}
    return {user.id: user for user in db.scalars(select(User).where(User.id.in_(ids)))}


def list_active_technicians(db: Session) -> Sequence[User]:
    query = (
        select(User)
        .where(User.role == Role.TECHNICIAN, User.is_active.is_(True))
        .order_by(User.full_name, User.id)
    )
    return db.scalars(query).all()


def list_requesters_with_opt_in(db: Session) -> Sequence[User]:
    query = (
        select(User)
        .where(User.role == Role.REQUESTER, User.whatsapp_opt_in.is_(True))
        .order_by(User.full_name, User.id)
    )
    return db.scalars(query).all()


def count(db: Session) -> int:
    return db.scalar(select(func.count(User.id))) or 0


def add(db: Session, user: User) -> User:
    db.add(user)
    db.flush()
    return user
