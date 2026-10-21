"""Simulador de WhatsApp (sección 13.4): no sale nada a la red.

El mensaje queda con estado SIMULATED y se muestra en la página /simulador.
"""

import uuid

from backend.integrations.base import OutgoingMessage, SendResult
from backend.models.enums import NotificationChannel, NotificationStatus


class SimulatedWhatsApp:
    channel = NotificationChannel.SIMULATED

    def send(self, message: OutgoingMessage) -> SendResult:
        return SendResult(
            status=NotificationStatus.SIMULATED,
            provider_message_id=f"sim-{uuid.uuid4().hex}",
        )
