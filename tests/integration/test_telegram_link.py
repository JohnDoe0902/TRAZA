"""Vincular la cuenta de TRAZA con Telegram: el enlace, /start y la página /telegram."""

from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.core.clock import utcnow
from backend.models import User
from backend.services import telegram_bot_service, telegram_link_service
from backend.services.telegram_link_service import LinkOutcome
from tests.helpers import Actors
from tests.telegram_fakes import FakeTelegram, text_update, use_telegram

CHAT_ID = 900_000_001


@pytest.fixture(autouse=True)
def _telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    use_telegram(monkeypatch)


def token_of(db: Session, user: User) -> str:
    link = telegram_link_service.create_link(db, user, utcnow())
    return link.url.split("start=")[1]


def test_el_enlace_apunta_al_bot_y_vence(db: Session, actors: Actors) -> None:
    now = utcnow()

    link = telegram_link_service.create_link(db, actors.requester, now)

    assert link.url.startswith("https://t.me/traza_prueba_bot?start=")
    assert link.expires_at == now + timedelta(minutes=30)
    assert actors.requester.telegram_link_token in link.url


def test_start_con_token_vincula_y_el_token_se_borra(db: Session, actors: Actors) -> None:
    token = token_of(db, actors.requester)

    result = telegram_link_service.link_chat(db, token, CHAT_ID, utcnow())

    assert result.outcome == LinkOutcome.LINKED
    assert actors.requester.telegram_chat_id == CHAT_ID
    assert actors.requester.telegram_link_token is None


def test_el_mismo_enlace_dos_veces_no_es_error(db: Session, actors: Actors) -> None:
    token = token_of(db, actors.requester)
    telegram_link_service.link_chat(db, token, CHAT_ID, utcnow())

    again = telegram_link_service.link_chat(db, token, CHAT_ID, utcnow())

    assert again.outcome == LinkOutcome.ALREADY_LINKED


def test_enlace_vencido_no_vincula(db: Session, actors: Actors) -> None:
    token = token_of(db, actors.requester)

    result = telegram_link_service.link_chat(db, token, CHAT_ID, utcnow() + timedelta(hours=1))

    assert result.outcome == LinkOutcome.EXPIRED
    assert actors.requester.telegram_chat_id is None
    assert actors.requester.telegram_link_token is None


def test_token_inventado_no_vincula(db: Session) -> None:
    result = telegram_link_service.link_chat(db, "no-existe", CHAT_ID, utcnow())

    assert result.outcome == LinkOutcome.INVALID


def test_un_chat_no_puede_ser_de_dos_cuentas(db: Session, actors: Actors) -> None:
    telegram_link_service.link_chat(db, token_of(db, actors.requester), CHAT_ID, utcnow())

    other = telegram_link_service.link_chat(db, token_of(db, actors.technician), CHAT_ID, utcnow())

    assert other.outcome == LinkOutcome.CHAT_IN_USE
    assert actors.technician.telegram_chat_id is None


def test_un_enlace_nuevo_invalida_el_anterior(db: Session, actors: Actors) -> None:
    old_token = token_of(db, actors.requester)
    token_of(db, actors.requester)

    result = telegram_link_service.link_chat(db, old_token, CHAT_ID, utcnow())

    assert result.outcome == LinkOutcome.INVALID


def test_desvincular(db: Session, actors: Actors) -> None:
    telegram_link_service.link_chat(db, token_of(db, actors.requester), CHAT_ID, utcnow())

    telegram_link_service.unlink(db, actors.requester)

    assert actors.requester.telegram_chat_id is None


# --- Lo que contesta el bot ---------------------------------------------------------------------


def test_el_bot_contesta_al_vincular(db: Session, actors: Actors) -> None:
    bot = FakeTelegram()
    update = text_update(CHAT_ID, f"/start {token_of(db, actors.requester)}")

    telegram_bot_service.handle_update(db, bot, update, utcnow())

    assert actors.requester.telegram_chat_id == CHAT_ID
    assert bot.sent[0].text == telegram_bot_service.LINK_REPLIES[LinkOutcome.LINKED]


def test_sin_token_el_bot_explica_que_hacer(db: Session) -> None:
    bot = FakeTelegram()

    telegram_bot_service.handle_update(db, bot, text_update(CHAT_ID, "hola"), utcnow())

    assert bot.sent[0].text == telegram_bot_service.HELP_TEXT


def test_el_bot_ignora_los_grupos(db: Session, actors: Actors) -> None:
    bot = FakeTelegram()
    update = text_update(CHAT_ID, f"/start {token_of(db, actors.requester)}", chat_type="group")

    telegram_bot_service.handle_update(db, bot, update, utcnow())

    assert bot.sent == []
    assert actors.requester.telegram_chat_id is None


# --- Página /telegram ---------------------------------------------------------------------------


def test_pagina_muestra_el_enlace_y_luego_vinculado(
    db: Session, actors: Actors, login: Callable[[User], TestClient]
) -> None:
    client = login(actors.requester)

    assert "No vinculado" in client.get("/telegram").text
    page = client.post("/telegram/vincular").text
    assert "https://t.me/traza_prueba_bot?start=" in page

    db.refresh(actors.requester)
    token = actors.requester.telegram_link_token
    assert token is not None
    telegram_link_service.link_chat(db, token, CHAT_ID, utcnow())
    assert "Vinculado" in client.get("/telegram").text


def test_pagina_permite_desvincular(
    db: Session, actors: Actors, login: Callable[[User], TestClient]
) -> None:
    telegram_link_service.link_chat(db, token_of(db, actors.requester), CHAT_ID, utcnow())
    client = login(actors.requester)

    response = client.post("/telegram/desvincular", follow_redirects=True)

    assert "Desvinculaste tu Telegram" in response.text
    db.refresh(actors.requester)
    assert actors.requester.telegram_chat_id is None


def test_pagina_pide_iniciar_sesion(client: TestClient) -> None:
    response = client.get("/telegram", follow_redirects=False)

    assert response.status_code in (303, 307)
