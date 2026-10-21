"""RF-05 a RF-07, RN-04, RN-05 y regla 4: clasificación con mock, reglas y fallback."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.integrations.mock_provider import MockProvider
from backend.integrations.rule_provider import RuleProvider
from backend.models import Classification
from backend.models.enums import (
    Category,
    ClassificationProvider,
    EventType,
    JobType,
    Priority,
)
from backend.services import classification_service
from tests.helpers import Actors, FailingClassifier, events_of, jobs_of, new_ticket


def classify(db: Session, ticket_id: int, provider=None) -> Classification | None:  # noqa: ANN001
    return classification_service.classify_ticket(
        db,
        ticket_id,
        uuid.uuid4(),
        provider=provider or MockProvider(),
        fallback=RuleProvider(),
    )


def test_rf05_clasificacion_guarda_fila_evento_y_prioridad(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)  # laboratorio sin internet, con clase

    classification = classify(db, ticket.id)

    assert classification is not None
    assert classification.provider == ClassificationProvider.MOCK
    assert classification.priority_computed == Priority.CRITICA
    assert classification.rules_version == "v1"
    assert classification.confidence == Decimal("0.93")
    assert ticket.category == Category.REDES
    assert ticket.priority == Priority.CRITICA
    assert ticket.review_required is False
    classified = events_of(db, ticket, EventType.TICKET_CLASSIFIED)[0]
    assert classified.safe_details_json["priority"] == "CRITICA"
    assert classified.actor_type == "SYSTEM"
    assert JobType.AUTO_ASSIGN in [job.job_type for job in jobs_of(db, ticket)]


def test_regla4_seguridad_pide_revision_y_no_autoasigna(db: Session, actors: Actors) -> None:
    ticket = new_ticket(
        db,
        actors.requester,
        title="Correo sospechoso",
        description="Posible exposición de credenciales por un correo sospechoso",
    )

    classify(db, ticket.id)

    assert ticket.category == Category.SEGURIDAD
    assert ticket.review_required is True
    assert JobType.AUTO_ASSIGN not in [job.job_type for job in jobs_of(db, ticket)]


def test_regla4_la_prioridad_sale_de_la_matriz_no_del_proveedor(
    db: Session, actors: Actors
) -> None:
    """Aunque el proveedor devuelva un campo 'priority', el esquema lo rechaza y se usa reglas."""

    class PriorityWriter:
        name = ClassificationProvider.OPENAI
        model_version = "fake"

        def classify(self, text):  # noqa: ANN001, ANN202
            return {
                "category": "REDES",
                "impact": "INDIVIDUAL",
                "urgency": "BAJA",
                "priority": "CRITICA",
            }

    ticket = new_ticket(db, actors.requester, title="Mouse", description="El mouse no funciona")
    classification = classify(db, ticket.id, PriorityWriter())

    assert classification.provider == ClassificationProvider.RULES
    assert events_of(db, ticket, EventType.CLASSIFICATION_FALLBACK)


@pytest.mark.parametrize(
    ("failing", "reason"),
    [
        (FailingClassifier(error=TimeoutError("timeout")), "timeout"),
        (FailingClassifier(invalid_output=True), "invalid_output"),
        (FailingClassifier(error=RuntimeError("HTTP 500")), "provider_error"),
    ],
)
def test_rn05_fallback_a_reglas(
    db: Session, actors: Actors, failing: FailingClassifier, reason: str
) -> None:
    ticket = new_ticket(db, actors.requester)

    classification = classify(db, ticket.id, failing)

    assert classification is not None
    assert classification.provider == ClassificationProvider.RULES
    assert ticket.priority is not None  # el ticket se clasifica igual (RF-07)
    fallback = events_of(db, ticket, EventType.CLASSIFICATION_FALLBACK)
    assert len(fallback) == 1
    assert fallback[0].safe_details_json["reason"] == reason
    types = [e.event_type for e in events_of(db, ticket)]
    assert types.index(EventType.CLASSIFICATION_FALLBACK) < types.index(EventType.TICKET_CLASSIFIED)


def test_clasificacion_es_idempotente(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)
    classify(db, ticket.id)

    assert classify(db, ticket.id) is None
    rows = db.scalars(select(Classification).where(Classification.ticket_id == ticket.id)).all()
    assert len(rows) == 1


def test_al_clasificador_no_se_envian_datos_personales(db: Session, actors: Actors) -> None:
    seen = []

    class Spy(MockProvider):
        def classify(self, text):  # noqa: ANN001, ANN202
            seen.append(text)
            return super().classify(text)

    ticket = new_ticket(db, actors.requester)
    classify(db, ticket.id, Spy())

    sent = repr(seen[0])
    assert actors.requester.full_name not in sent
    assert actors.requester.email not in sent
    assert actors.requester.phone_e164 not in sent
