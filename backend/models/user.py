from datetime import datetime

from sqlalchemy import BigInteger, String, false, true
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, CommonColumnsMixin, str_enum, tz_datetime
from backend.models.enums import Role


class User(CommonColumnsMixin, Base):
    __tablename__ = "users"

    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    phone_e164: Mapped[str | None] = mapped_column(String(16))
    role: Mapped[Role] = mapped_column(str_enum(Role, "role"))
    whatsapp_opt_in: Mapped[bool] = mapped_column(default=False, server_default=false())
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())

    # Telegram no deja escribirle a nadie por su número. La persona abre el bot con su
    # token de vinculación y recién ahí guardamos su chat_id
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    telegram_link_token: Mapped[str | None] = mapped_column(String(64), unique=True)
    telegram_link_expires_at: Mapped[datetime | None] = mapped_column(tz_datetime())

    def __repr__(self) -> str:
        return f"<User id={self.id} role={self.role}>"
