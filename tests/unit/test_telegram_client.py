"""Cliente de Telegram con un transporte falso: se ve qué se manda sin salir a internet."""

import json
import logging

import httpx2
import pytest

from backend.integrations.telegram_client import InlineButton, TelegramClient, TelegramError

TOKEN = "123:token-de-prueba"


def client_with(handler) -> tuple[TelegramClient, list[httpx2.Request]]:  # noqa: ANN001
    calls: list[httpx2.Request] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return handler(request)

    http = httpx2.Client(transport=httpx2.MockTransport(record))
    return TelegramClient(TOKEN, http=http), calls


def ok(result: object) -> httpx2.Response:
    return httpx2.Response(200, json={"ok": True, "result": result})


def test_send_message_con_botones() -> None:
    client, calls = client_with(lambda request: ok({"message_id": 77}))

    message_id = client.send_message(55, "Hola", [InlineButton("Sí", "c:1:YES")])

    assert message_id == 77
    assert calls[0].url.path == f"/bot{TOKEN}/sendMessage"
    body = json.loads(calls[0].content)
    assert body == {
        "chat_id": 55,
        "text": "Hola",
        "reply_markup": {"inline_keyboard": [[{"text": "Sí", "callback_data": "c:1:YES"}]]},
    }


def test_send_message_sin_botones_no_manda_teclado() -> None:
    client, calls = client_with(lambda request: ok({"message_id": 1}))

    client.send_message(55, "Hola")

    assert "reply_markup" not in json.loads(calls[0].content)


def test_get_updates_pasa_offset_y_espera() -> None:
    client, calls = client_with(lambda request: ok([{"update_id": 9}]))

    updates = client.get_updates(offset=9, timeout_seconds=25)

    assert updates == [{"update_id": 9}]
    body = json.loads(calls[0].content)
    assert body["offset"] == 9
    assert body["timeout"] == 25


def test_error_400_no_se_reintenta() -> None:
    client, _ = client_with(
        lambda request: httpx2.Response(400, json={"ok": False, "description": "chat not found"})
    )

    with pytest.raises(TelegramError) as error:
        client.send_message(55, "Hola")

    assert error.value.retryable is False
    assert "chat not found" in str(error.value)


def test_error_500_si_se_puede_reintentar() -> None:
    client, _ = client_with(lambda request: httpx2.Response(502, json={"ok": False}))

    with pytest.raises(TelegramError) as error:
        client.send_message(55, "Hola")

    assert error.value.retryable is True


def test_un_corte_de_red_no_filtra_el_token() -> None:
    def cut(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError(f"no se pudo conectar a {request.url}")

    client, _ = client_with(cut)

    with pytest.raises(TelegramError) as error:
        client.send_message(55, "Hola")

    # El mensaje de httpx trae la URL y la URL trae el token. No debe aparecer
    assert TOKEN not in str(error.value)
    assert error.value.__cause__ is None


def test_sin_token_no_arranca() -> None:
    with pytest.raises(ValueError):
        TelegramClient("")


def test_los_logs_de_httpx2_no_muestran_el_token(caplog: pytest.LogCaptureFixture) -> None:
    client, _ = client_with(lambda request: ok({"message_id": 1}))

    with caplog.at_level(logging.INFO):
        client.send_message(55, "Hola")

    assert TOKEN not in caplog.text


def test_get_me_devuelve_el_nombre_del_bot() -> None:
    client, calls = client_with(lambda request: ok({"id": 1, "username": "mi_bot"}))

    assert client.get_bot_username() == "mi_bot"
    assert calls[0].url.path == f"/bot{TOKEN}/getMe"
