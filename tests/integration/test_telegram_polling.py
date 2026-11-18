"""Proceso que escucha al bot: el offset avanza y un update roto no lo traba."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy.orm import Session

from backend.services import telegram_bot_service
from backend.workers import telegram_bot
from tests.telegram_fakes import FakeTelegram, text_update


class FakePollingClient(FakeTelegram):
    """Devuelve los updates por tandas y anota con qué offset le preguntaron."""

    def __init__(self, batches: list[list[dict[str, Any]]]) -> None:
        super().__init__()
        self.batches = batches
        self.offsets: list[int | None] = []

    def get_updates(self, offset: int | None, timeout_seconds: int) -> list[dict[str, Any]]:
        self.offsets.append(offset)
        return self.batches.pop(0) if self.batches else []


@pytest.fixture(autouse=True)
def _use_test_session(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    @contextmanager
    def session() -> Iterator[Session]:
        yield db

    monkeypatch.setattr(telegram_bot, "SessionLocal", session)


def test_drain_confirma_lo_procesado_con_el_offset() -> None:
    first, second = text_update(1, "hola"), text_update(1, "hola")
    client = FakePollingClient([[first, second]])

    telegram_bot.drain(client)  # type: ignore[arg-type]

    # La segunda pregunta lleva el offset siguiente y eso le confirma a Telegram lo leído
    assert client.offsets == [None, second["update_id"] + 1]
    assert len(client.sent) == 2


def test_un_update_que_falla_no_traba_al_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    broken, fine = text_update(1, "rompe"), text_update(1, "hola")
    original = telegram_bot_service.handle_update

    def handle(db: Session, bot: Any, update: dict[str, Any], now: Any) -> None:
        if update is broken:
            raise RuntimeError("update raro")
        original(db, bot, update, now)

    monkeypatch.setattr(telegram_bot_service, "handle_update", handle)
    client = FakePollingClient([[broken, fine]])

    next_offset = telegram_bot.poll_once(client, None, 0)  # type: ignore[arg-type]

    assert next_offset == fine["update_id"] + 1
    assert len(client.sent) == 1
