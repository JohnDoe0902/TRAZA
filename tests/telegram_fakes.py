"""Telegram falso para las pruebas. Nunca sale nada a la red."""

import itertools
from dataclasses import dataclass, field
from typing import Any

import pytest

from backend.core.config import get_settings
from backend.integrations.telegram_client import InlineButton

_update_ids = itertools.count(1000)
_callback_ids = itertools.count(1)


@dataclass
class SentMessage:
    chat_id: int
    text: str
    buttons: list[InlineButton] | None


@dataclass
class FakeTelegram:
    """Sirve como cliente para el canal y como bot para el servicio de updates."""

    sent: list[SentMessage] = field(default_factory=list)
    callback_answers: list[str] = field(default_factory=list)
    removed_buttons: list[tuple[int, int]] = field(default_factory=list)
    fail_sends: bool = False
    _message_ids: itertools.count = field(default_factory=lambda: itertools.count(1))

    def send_message(
        self,
        chat_id: int,
        text: str,
        buttons: list[InlineButton] | None = None,
        *,
        html: bool = False,
    ) -> int:
        if self.fail_sends:
            raise ConnectionError("Telegram caído (simulado)")
        self.sent.append(SentMessage(chat_id, text, buttons))
        return next(self._message_ids)

    def answer_callback(self, callback_query_id: str, text: str) -> None:
        self.callback_answers.append(text)

    def remove_buttons(self, chat_id: int, message_id: int) -> None:
        self.removed_buttons.append((chat_id, message_id))


def use_telegram(monkeypatch: pytest.MonkeyPatch, bot_username: str = "traza_prueba_bot") -> None:
    """Hace que la prueba corra como si NOTIFICATION_PROVIDER fuera telegram."""
    settings = get_settings()
    monkeypatch.setattr(settings, "notification_provider", "telegram")
    monkeypatch.setattr(settings, "telegram_bot_username", bot_username)
    # Sin token la fábrica no le pregunta nada al Telegram real y usa el nombre de arriba
    monkeypatch.setattr(settings, "telegram_bot_token", None)


def text_update(chat_id: int, text: str, chat_type: str = "private") -> dict[str, Any]:
    return {
        "update_id": next(_update_ids),
        "message": {"message_id": 1, "chat": {"id": chat_id, "type": chat_type}, "text": text},
    }


def button_update(
    chat_id: int, data: str, message_id: int = 1, callback_id: str | None = None
) -> dict[str, Any]:
    """Como lo manda Telegram cuando alguien pulsa un botón."""
    return {
        "update_id": next(_update_ids),
        "callback_query": {
            "id": callback_id or f"cb-{next(_callback_ids)}",
            "from": {"id": chat_id},
            "data": data,
            "message": {"message_id": message_id, "chat": {"id": chat_id, "type": "private"}},
        },
    }
