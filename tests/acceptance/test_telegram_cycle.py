"""Prueba de aceptación del ciclo completo por Telegram (D-41).

vincular → alta → clasificación → asignación → atención → solución → No → retoma →
solución → Sí → cerrado

Cada persona usa la web como lo haría de verdad. Lo que pasa en el celular lo simula un
Telegram falso: los mensajes que "llegan" y los botones que se pulsan. Nunca sale nada a la red.
"""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.core.clock import utcnow
from backend.integrations.telegram_channel import TelegramChannel
from backend.models import User
from backend.models.enums import ConfirmationSource, NotificationStatus, Priority, TicketStatus
from backend.repositories import (
    confirmation_repository,
    notification_repository,
    ticket_repository,
)
from backend.services import telegram_bot_service
from backend.workers.process_outbox import drain
from tests.helpers import VALID_TICKET, Actors, fake_providers
from tests.telegram_fakes import FakeTelegram, button_update, text_update, use_telegram

Login = Callable[[User], TestClient]

REQUESTER_CHAT = 811_000_001
TECHNICIAN_CHAT = 811_000_002


class Phone:
    """El celular de cada persona: lo que le llegó y los botones que puede pulsar."""

    def __init__(self, telegram: FakeTelegram, db: Session) -> None:
        self.telegram = telegram
        self.db = db

    def open_link(self, chat_id: int, link_page: str) -> None:
        token = link_page.split("?start=")[1].split('"')[0]
        update = text_update(chat_id, f"/start {token}")
        telegram_bot_service.handle_update(self.db, self.telegram, update, utcnow())

    def inbox(self, chat_id: int) -> list[str]:
        return [m.text.splitlines()[0] for m in self.telegram.sent if m.chat_id == chat_id]

    def press(self, chat_id: int, label: str) -> None:
        """Pulsa el botón con ese texto en la última pregunta que llegó a ese chat."""
        question = [m for m in self.telegram.sent if m.chat_id == chat_id and m.buttons][-1]
        button = next(b for b in question.buttons or [] if b.text == label)
        update = button_update(chat_id, button.callback_data)
        telegram_bot_service.handle_update(self.db, self.telegram, update, utcnow())


def test_ciclo_completo_por_telegram(
    db: Session, actors: Actors, login: Login, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_telegram(monkeypatch)
    telegram = FakeTelegram()
    phone = Phone(telegram, db)
    providers = fake_providers(notifier=TelegramChannel(telegram))  # type: ignore[arg-type]

    def run_worker() -> None:
        drain(db, providers=providers)

    requester = login(actors.requester)
    technician = login(actors.technician)

    # 0. Solicitante y técnico vinculan su Telegram desde la web
    phone.open_link(REQUESTER_CHAT, requester.post("/telegram/vincular").text)
    phone.open_link(TECHNICIAN_CHAT, technician.post("/telegram/vincular").text)
    assert "Vinculado" in requester.get("/telegram").text

    # 1. Alta en la web
    created = requester.post("/api/tickets", json=VALID_TICKET)
    assert created.status_code == 201
    code = created.json()["public_code"]
    ticket = ticket_repository.get_by_code(db, code)
    assert ticket is not None

    # 2-3. El worker clasifica, asigna y avisa por Telegram
    run_worker()
    db.refresh(ticket)
    assert (ticket.priority, ticket.status) == (Priority.CRITICA, TicketStatus.ASIGNADO)
    assert ticket.assigned_technician_id == actors.technician.id

    # 4-5. El técnico atiende y propone la solución. Al celular llega la pregunta
    technician.post(f"/api/tickets/{code}/start", json={})
    technician.post(
        f"/api/tickets/{code}/resolve",
        json={"resolution_text": "Se reinició el switch del laboratorio 3."},
    )
    run_worker()

    # 6. "No, continúa" desde Telegram → reabierto y aviso al técnico en su Telegram
    phone.press(REQUESTER_CHAT, "No, continúa")
    run_worker()
    db.refresh(ticket)
    assert ticket.status == TicketStatus.REABIERTO

    # 7-8. El técnico retoma y propone otra solución
    technician.post(f"/api/tickets/{code}/start", json={})
    technician.post(
        f"/api/tickets/{code}/resolve",
        json={"resolution_text": "Se reemplazó el cable dañado del rack del laboratorio."},
    )
    run_worker()

    # 9. "Sí, se solucionó" desde Telegram → cerrado
    phone.press(REQUESTER_CHAT, "Sí, se solucionó")
    run_worker()
    db.refresh(ticket)
    assert ticket.status == TicketStatus.CERRADO
    assert ticket.reopen_count == 1

    # Lo que vio cada celular, en orden, con el diseño de Telegram
    assert phone.inbox(REQUESTER_CHAT) == [
        "✅ ¡Listo! Tu cuenta de TRAZA quedó vinculada.",
        "📥 <b>Solicitud registrada</b>",
        "👨‍🔧 <b>Técnico asignado</b>",
        "🛠️ <b>Solución registrada</b>",
        "🔄 <b>Solicitud reabierta</b>",
        "🛠️ <b>Solución registrada</b>",
        "✅ <b>Solicitud cerrada</b>",
    ]
    assert "🔁 <b>El problema continúa</b>" in phone.inbox(TECHNICIAN_CHAT)

    # Las dos respuestas quedaron guardadas como venidas de Telegram, una por ronda
    confirmations = confirmation_repository.list_for_ticket(db, ticket.id)
    assert [(c.confirmation_round, c.source) for c in confirmations] == [
        (1, ConfirmationSource.TELEGRAM),
        (2, ConfirmationSource.TELEGRAM),
    ]
    # Regla 9: todos los avisos quedaron como enviados, ninguno como "entregado"
    statuses = {n.status for n in notification_repository.list_for_ticket(db, ticket.id)}
    assert statuses == {NotificationStatus.SENT}
