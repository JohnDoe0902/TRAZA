"""Cliente mínimo de la API de bots de Telegram (https://core.telegram.org/bots/api).

Solo sabe hablar con Telegram. No conoce tickets ni usuarios, eso lo deciden los servicios.
Nunca escribimos el token en los logs porque con él cualquiera controla el bot.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx2

API_URL = "https://api.telegram.org"

# httpx2 anota cada pedido con la URL completa y en Telegram la URL lleva el token.
# Lo subimos a WARNING para que el token nunca termine en un log
logging.getLogger("httpx2").setLevel(logging.WARNING)


class TelegramError(RuntimeError):
    """Telegram no respondió o rechazó el pedido."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        # Un 400 por datos malos no se arregla reintentando. Un 500 o un timeout sí puede
        self.retryable = retryable


@dataclass(frozen=True)
class InlineButton:
    text: str
    callback_data: str


class TelegramClient:
    def __init__(
        self, token: str, *, timeout: float = 10, http: httpx2.Client | None = None
    ) -> None:
        if not token:
            raise ValueError("Falta el token del bot de Telegram.")
        self._base = f"{API_URL}/bot{token}"
        self._http = http or httpx2.Client(timeout=timeout)

    def send_message(
        self, chat_id: int, text: str, buttons: list[InlineButton] | None = None
    ) -> int:
        """Manda un texto y devuelve el id del mensaje en Telegram."""
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if buttons:
            # Todos los botones van en una sola fila. Para Sí y No queda bien
            row = [{"text": b.text, "callback_data": b.callback_data} for b in buttons]
            payload["reply_markup"] = {"inline_keyboard": [row]}
        result = self._call("sendMessage", payload)
        return int(result["message_id"])

    def get_updates(self, offset: int | None, timeout_seconds: int) -> list[dict[str, Any]]:
        """Pide lo que llegó al bot. Con timeout > 0 Telegram espera hasta que haya algo."""
        payload: dict[str, Any] = {
            "timeout": timeout_seconds,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        # La espera larga necesita un timeout HTTP un poco mayor que el de Telegram
        result = self._call("getUpdates", payload, timeout=timeout_seconds + 10)
        return list(result)

    def answer_callback(self, callback_query_id: str, text: str) -> None:
        """Quita el relojito del botón y muestra un aviso corto arriba del chat."""
        self._call("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})

    def remove_buttons(self, chat_id: int, message_id: int) -> None:
        """Saca los botones de un mensaje para que no se vuelvan a pulsar."""
        self._call(
            "editMessageReplyMarkup",
            {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []}},
        )

    def _call(self, method: str, payload: dict[str, Any], timeout: float | None = None) -> Any:
        try:
            response = self._http.post(
                f"{self._base}/{method}",
                json=payload,
                **({"timeout": timeout} if timeout is not None else {}),
            )
        except httpx2.HTTPError as exc:
            # Solo el tipo de error. El mensaje completo puede traer la URL con el token
            raise TelegramError(f"{method}: {type(exc).__name__}") from None

        try:
            data = response.json()
        except ValueError:
            raise TelegramError(
                f"{method}: respuesta no es JSON ({response.status_code})"
            ) from None

        if response.status_code >= 400 or not data.get("ok"):
            description = str(data.get("description", "sin detalle"))[:200]
            retryable = response.status_code >= 500 or response.status_code == 429
            raise TelegramError(
                f"{method}: {response.status_code} {description}", retryable=retryable
            )
        return data["result"]
