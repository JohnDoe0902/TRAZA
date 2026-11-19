"""Proceso que escucha al bot de Telegram (polling).

Uso:
    python -m backend.workers.telegram_bot          # se queda escuchando
    python -m backend.workers.telegram_bot --once   # procesa lo pendiente y termina

Preguntamos a Telegram con getUpdates y espera larga. Así funciona en una PC normal sin
HTTPS ni túnel, que es lo que necesitamos para la demo. Va aparte del worker de la cola
porque cada pedido puede quedarse esperando hasta 25 segundos.

El offset le dice a Telegram qué updates ya procesamos. Si el proceso se reinicia solo
vuelven los que no confirmamos, y esos no duplican nada porque todo es idempotente.
"""

import argparse
import logging
import time
from typing import Any

from backend.core.clock import utcnow
from backend.core.config import ConfigurationError
from backend.core.db import SessionLocal
from backend.integrations import factory
from backend.integrations.telegram_client import TelegramClient, TelegramError
from backend.services import telegram_bot_service

logger = logging.getLogger("traza.telegram")

LONG_POLL_SECONDS = 25
PAUSE_AFTER_ERROR_SECONDS = 5


def process_updates(client: TelegramClient, updates: list[dict[str, Any]]) -> int | None:
    """Atiende cada update en su propia sesión. Devuelve el próximo offset."""
    next_offset: int | None = None
    for update in updates:
        try:
            with SessionLocal() as db:
                telegram_bot_service.handle_update(db, client, update, utcnow())
        except Exception as exc:
            # Un update raro no puede trabar al bot para siempre. Lo saltamos y seguimos
            logger.error("Update %s falló: %s", update.get("update_id"), type(exc).__name__)
        next_offset = int(update["update_id"]) + 1
    return next_offset


def poll_once(client: TelegramClient, offset: int | None, wait_seconds: int) -> int | None:
    updates = client.get_updates(offset, wait_seconds)
    return process_updates(client, updates) or offset


def drain(client: TelegramClient, max_rounds: int = 20) -> None:
    """Procesa todo lo pendiente sin esperar. La última vuelta confirma el offset en Telegram."""
    offset: int | None = None
    for _ in range(max_rounds):
        new_offset = poll_once(client, offset, 0)
        if new_offset == offset:
            return
        offset = new_offset


def main() -> None:
    parser = argparse.ArgumentParser(description="Escucha el bot de Telegram de TRAZA")
    parser.add_argument("--once", action="store_true", help="procesa lo pendiente y termina")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        client = factory.telegram_client()
    except ConfigurationError as exc:
        logger.error("No se puede iniciar el bot: %s", exc)
        raise SystemExit(2) from exc

    if args.once:
        try:
            drain(client)
        except TelegramError as exc:
            logger.warning("Telegram no respondió: %s", exc)
            raise SystemExit(1) from exc
        logger.info("Listo, no quedan mensajes pendientes")
        return

    logger.info("Bot de Telegram escuchando")
    offset: int | None = None
    try:
        while True:
            try:
                offset = poll_once(client, offset, LONG_POLL_SECONDS)
            except TelegramError as exc:
                logger.warning("Telegram no respondió: %s", exc)
                time.sleep(PAUSE_AFTER_ERROR_SECONDS)
    except KeyboardInterrupt:
        # Ctrl+C. Lo que no confirmamos con el offset vuelve en el próximo arranque
        logger.info("Bot de Telegram detenido")


if __name__ == "__main__":
    main()
