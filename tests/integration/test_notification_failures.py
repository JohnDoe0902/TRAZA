"""Aviso A6 al administrador cuando un mensaje no se pudo enviar (CP-10, guía B-4)."""

from collections.abc import Callable
from datetime import timedelta

from sqlalchemy.orm import Session

from backend.core.clock import utcnow
from backend.models import Notification, Ticket, User
from backend.models.enums import MessageType, NotificationStatus, Role, TicketStatus
from backend.workers.process_outbox import process_batch
from tests.helpers import Actors, FailingNotifier, fake_providers, new_ticket, notifications_of

# Esperas del worker entre intentos (1, 2, 4 y 8 minutos) para llegar al quinto
RETRY_WAITS = (0, 1, 2, 4, 8)


def run_until_exhausted(db: Session, notifier: FailingNotifier) -> None:
    """Corre el worker justo en el momento de cada reintento hasta agotarlos."""
    providers = fake_providers(notifier=notifier)
    when = utcnow()
    for wait in RETRY_WAITS:
        when += timedelta(minutes=wait)
        process_batch(db, providers=providers, now=when)


def of_type(db: Session, ticket: Ticket, message_type: MessageType) -> list[Notification]:
    return [n for n in notifications_of(db, ticket) if n.message_type == message_type]


def test_cp10_al_agotar_intentos_se_avisa_al_admin_con_a6(
    db: Session, actors: Actors, make_user: Callable[..., User]
) -> None:
    admin = make_user(Role.ADMIN, whatsapp_opt_in=True, full_name="Ana Torres")
    ticket = new_ticket(db, actors.requester)

    run_until_exhausted(db, FailingNotifier())

    db.refresh(ticket)
    # La falla de mensajería no frena ni cierra el ticket. Sigue su curso normal
    assert ticket.status == TicketStatus.ASIGNADO
    (a1,) = of_type(db, ticket, MessageType.A1)
    assert a1.status == NotificationStatus.FAILED
    (a6,) = of_type(db, ticket, MessageType.A6)
    assert a6.recipient_user_id == admin.id
    assert ticket.public_code in a6.body
    assert "Intento 5" in a6.body


def test_si_falla_el_a6_no_se_manda_otro_a6(
    db: Session, actors: Actors, make_user: Callable[..., User]
) -> None:
    make_user(Role.ADMIN, whatsapp_opt_in=True)
    ticket = new_ticket(db, actors.requester)
    notifier = FailingNotifier()

    # El canal sigue caído así que el A6 también se agota
    run_until_exhausted(db, notifier)
    run_until_exhausted(db, notifier)

    a6 = of_type(db, ticket, MessageType.A6)
    assert len(a6) == 1
    assert a6[0].status == NotificationStatus.FAILED


def test_admin_inactivo_no_recibe_a6(
    db: Session, actors: Actors, make_user: Callable[..., User]
) -> None:
    make_user(Role.ADMIN, whatsapp_opt_in=True, is_active=False)
    ticket = new_ticket(db, actors.requester)

    run_until_exhausted(db, FailingNotifier())

    assert of_type(db, ticket, MessageType.A6) == []
