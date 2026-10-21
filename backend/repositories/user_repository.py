from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models import User


def get_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.lower()))


def count(db: Session) -> int:
    return db.scalar(select(func.count(User.id))) or 0


def add(db: Session, user: User) -> User:
    db.add(user)
    db.flush()
    return user
