"""Worker de la cola `outbox_jobs` (sección 13.5).

Uso:
    python -m backend.workers.process_outbox          # bucle cada OUTBOX_POLL_SECONDS
    python -m backend.workers.process_outbox --once   # un solo ciclo (demo y pruebas)

Cada trabajo corre en su propia transacción y todos los manejadores son idempotentes: si un
trabajo se repite (por ejemplo, tras recuperar uno abandonado), no duplica efectos.
"""

import argparse
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from backend.core.clock import utcnow
from backend.core.config import ConfigurationError, get_settings
from backend.core.db import SessionLocal
from backend.integrations import factory
from backend.integrations.base import (
    ClassificationProvider,
    MessageComposer,
    NotificationProvider,
)
from backend.models import OutboxJob
from backend.models.enums import JobType
from backend.services import (
    assignment_service,
    classification_service,
    notification_service,
    outbox_service,
)

logger = logging.getLogger("traza.worker")
BATCH_SIZE = 20


@dataclass
class Providers:
    classifier: ClassificationProvider = field(default_factory=factory.get_classifier)
    fallback_classifier: ClassificationProvider = field(
        default_factory=factory.get_fallback_classifier
    )
    notifier: NotificationProvider = field(default_factory=factory.get_notification_provider)
    composer: MessageComposer = field(default_factory=factory.get_composer)


Handler = Callable[[Session, OutboxJob, Providers], None]


def _correlation_id(job: OutboxJob) -> uuid.UUID:
    value = job.payload_safe_json.get("correlation_id")
    return uuid.UUID(value) if value else uuid.uuid4()


def _classify(db: Session, job: OutboxJob, providers: Providers) -> None:
    classification_service.classify_ticket(
        db,
        int(job.payload_safe_json["ticket_id"]),
        _correlation_id(job),
        provider=providers.classifier,
        fallback=providers.fallback_classifier,
    )


def _auto_assign(db: Session, job: OutboxJob, providers: Providers) -> None:
    assignment_service.auto_assign(
        db, int(job.payload_safe_json["ticket_id"]), _correlation_id(job)
    )


def _send_notification(db: Session, job: OutboxJob, providers: Providers) -> None:
    notification_service.deliver(
        db,
        int(job.payload_safe_json["notification_id"]),
        providers.notifier,
        _correlation_id(job),
        composer=providers.composer,
    )


HANDLERS: dict[JobType, Handler] = {
    JobType.CLASSIFY_TICKET: _classify,
    JobType.AUTO_ASSIGN: _auto_assign,
    JobType.SEND_NOTIFICATION: _send_notification,
}


def run_job(db: Session, job: OutboxJob, providers: Providers, now: datetime) -> bool:
    """Ejecuta un trabajo ya marcado RUNNING. Devuelve True si terminó bien."""
    job_id = job.id
    try:
        HANDLERS[job.job_type](db, job, providers)
        outbox_service.mark_done(db, job, now)
    except Exception as exc:
        db.rollback()
        logger.warning("Trabajo %s falló: %s", job_id, type(exc).__name__)
        outbox_service.mark_failed_attempt(db, job_id, exc, now)
        return False
    logger.info("Trabajo %s (%s) completado", job_id, job.job_type.value)
    return True


def process_batch(
    db: Session,
    *,
    providers: Providers | None = None,
    now: datetime | None = None,
    limit: int = BATCH_SIZE,
) -> int:
    """Un ciclo: recupera abandonados, toma los vencidos y los ejecuta. Devuelve cuántos tomó."""
    providers = providers or Providers()
    now = now or utcnow()
    recovered = outbox_service.recover_stale_jobs(db, now)
    if recovered:
        logger.warning("%s trabajos abandonados volvieron a PENDING", recovered)
    jobs = outbox_service.claim_due_jobs(db, now, limit)
    for job in jobs:
        run_job(db, job, providers, now)
    return len(jobs)


def drain(
    db: Session,
    *,
    providers: Providers | None = None,
    now: datetime | None = None,
    max_cycles: int = 20,
) -> int:
    """Procesa ciclos hasta que no quedan trabajos vencidos (útil en demo y pruebas)."""
    providers = providers or Providers()
    total = 0
    for _ in range(max_cycles):
        processed = process_batch(db, providers=providers, now=now)
        total += processed
        if processed == 0:
            break
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Worker de la cola outbox_jobs de TRAZA")
    parser.add_argument("--once", action="store_true", help="procesa un ciclo y termina")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        providers = Providers()
    except ConfigurationError as exc:
        logger.error("No se puede iniciar el worker: %s", exc)
        raise SystemExit(2) from exc
    poll_seconds = get_settings().outbox_poll_seconds
    logger.info(
        "Worker iniciado (cada %s s). Clasificador: %s · redactor: %s · mensajería: %s",
        poll_seconds,
        providers.classifier.name.value,
        providers.composer.name,
        providers.notifier.channel.value,
    )
    while True:
        with SessionLocal() as db:
            processed = (
                drain(db, providers=providers)
                if args.once
                else process_batch(db, providers=providers)
            )
        if args.once:
            logger.info("Ciclo único terminado: %s trabajos", processed)
            return
        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
