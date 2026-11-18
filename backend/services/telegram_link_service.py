"""Vincular la cuenta de TRAZA con el chat de Telegram de la persona.

Telegram no deja que un bot le escriba primero a nadie, ni siquiera sabiendo su número.
Por eso el flujo es así:

1. La persona entra a TRAZA y pide su enlace. Le damos t.me/<bot>?start=<token>.
2. Abre el enlace y pulsa Iniciar. Telegram le manda al bot "/start <token>".
3. Buscamos de quién es ese token, guardamos su chat_id y borramos el token.

El token es de un solo uso y vence a los TELEGRAM_LINK_MINUTES minutos.
"""

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

import segno
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.errors import BusinessRuleViolation
from backend.models import User
from backend.repositories import user_repository
from backend.services.uow import atomic

logger = logging.getLogger("traza.telegram")

# 24 bytes salen en 32 caracteres. Telegram acepta hasta 64 en el parámetro start
TOKEN_BYTES = 24
# Azul de Telegram para los módulos del QR
QR_COLOR = "#1d93d2"


class LinkOutcome(StrEnum):
    LINKED = "LINKED"
    ALREADY_LINKED = "ALREADY_LINKED"
    INVALID = "INVALID"
    EXPIRED = "EXPIRED"
    CHAT_IN_USE = "CHAT_IN_USE"


@dataclass(frozen=True)
class TelegramLink:
    url: str
    expires_at: datetime
    bot_username: str


@dataclass(frozen=True)
class LinkResult:
    outcome: LinkOutcome
    user: User | None = None


def is_linked(user: User) -> bool:
    return user.telegram_chat_id is not None


def create_link(db: Session, user: User, now: datetime, bot_username: str | None) -> TelegramLink:
    """Genera un enlace nuevo. Si había uno anterior deja de servir.

    `bot_username` llega ya resuelto (lo saca la fábrica a partir del token) así que el
    enlace abre el bot que de verdad está corriendo en esta PC.
    """
    if not bot_username:
        raise BusinessRuleViolation(
            "Falta configurar el bot: pon TELEGRAM_BOT_TOKEN en el .env de esta PC."
        )
    expires_at = now + timedelta(minutes=get_settings().telegram_link_minutes)
    with atomic(db):
        user.telegram_link_token = secrets.token_urlsafe(TOKEN_BYTES)
        user.telegram_link_expires_at = expires_at
    url = f"https://t.me/{bot_username}?start={user.telegram_link_token}"
    return TelegramLink(url=url, expires_at=expires_at, bot_username=bot_username)


def qr_svg(url: str) -> str:
    """Dibuja el enlace como QR en SVG, aquí mismo y sin servicios externos.

    Va con corrección de errores alta porque encima ponemos el avión de Telegram al
    centro. Así el código se sigue leyendo aunque el logo tape una parte.
    """
    code = segno.make(url, error="h")
    return code.svg_inline(dark=QR_COLOR, light=None, border=0, omitsize=True)


def link_chat(db: Session, token: str, chat_id: int, now: datetime) -> LinkResult:
    """Lo que pasa cuando llega "/start <token>" al bot."""
    user = user_repository.get_by_telegram_link_token(db, token) if token else None
    if user is None:
        return _already_linked_or_invalid(db, chat_id)
    if user.telegram_link_expires_at is None or user.telegram_link_expires_at < now:
        with atomic(db):
            _clear_token(user)
        return LinkResult(LinkOutcome.EXPIRED, user)

    owner = user_repository.get_by_telegram_chat_id(db, chat_id)
    if owner is not None and owner.id != user.id:
        # Un chat de Telegram es de una sola cuenta. Si no, alguien vería avisos ajenos
        return LinkResult(LinkOutcome.CHAT_IN_USE, user)

    try:
        with atomic(db):
            user.telegram_chat_id = chat_id
            _clear_token(user)
    except IntegrityError:
        # Otro proceso vinculó este chat justo ahora
        return LinkResult(LinkOutcome.CHAT_IN_USE, user)
    logger.info("Usuario %s vinculó su Telegram", user.id)
    return LinkResult(LinkOutcome.LINKED, user)


def unlink(db: Session, user: User) -> None:
    with atomic(db):
        user.telegram_chat_id = None
        _clear_token(user)
    logger.info("Usuario %s desvinculó su Telegram", user.id)


def _already_linked_or_invalid(db: Session, chat_id: int) -> LinkResult:
    # Si la persona vuelve a pulsar Iniciar con un token ya usado no es un error
    owner = user_repository.get_by_telegram_chat_id(db, chat_id)
    if owner is not None:
        return LinkResult(LinkOutcome.ALREADY_LINKED, owner)
    return LinkResult(LinkOutcome.INVALID)


def _clear_token(user: User) -> None:
    user.telegram_link_token = None
    user.telegram_link_expires_at = None
