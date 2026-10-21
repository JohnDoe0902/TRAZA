"""CP-06 y RN-05: si OpenAI falla, el ticket se clasifica igual con reglas."""

import pytest
from sqlalchemy.orm import Session

from backend.integrations.openai_provider import OpenAIClassificationOutput, OpenAIProvider
from backend.models.enums import (
    Category,
    ClassificationProvider,
    EventType,
    Impact,
    JobStatus,
    Priority,
    TicketStatus,
    Urgency,
)
from backend.repositories import classification_repository
from backend.workers.process_outbox import drain
from tests.helpers import (
    Actors,
    FakeOpenAIClient,
    events_of,
    fake_providers,
    jobs_of,
    new_ticket,
    openai_server_error,
    openai_timeout,
)


def test_cp06_caida_de_ia_por_timeout(db: Session, actors: Actors) -> None:
    """Timeout del proveedor → clasificado por reglas + CLASSIFICATION_FALLBACK (CP-06)."""
    ticket = new_ticket(db, actors.requester)
    client = FakeOpenAIClient(error=openai_timeout())
    providers = fake_providers(classifier=OpenAIProvider(client, "gpt-falso"))

    drain(db, providers=providers)

    db.refresh(ticket)
    assert len(client.calls) == 1  # se intentó una vez, sin reintentos que demoren el flujo
    classification = classification_repository.latest_for_ticket(db, ticket.id)
    assert classification.provider == ClassificationProvider.RULES
    assert ticket.priority is not None
    fallback = events_of(db, ticket, EventType.CLASSIFICATION_FALLBACK)
    assert len(fallback) == 1
    assert fallback[0].safe_details_json == {"reason": "timeout", "failed_provider": "openai"}
    # El resto del flujo sigue: el ticket se asigna y ningún trabajo quedó fallido.
    assert ticket.status == TicketStatus.ASIGNADO
    assert all(job.status == JobStatus.DONE for job in jobs_of(db, ticket))


@pytest.mark.parametrize(
    ("client", "reason"),
    [
        (FakeOpenAIClient(parsed=None), "invalid_output"),
        (
            FakeOpenAIClient(
                parsed=OpenAIClassificationOutput(
                    category=Category.REDES,
                    impact=Impact.AREA,
                    urgency=Urgency.ALTA,
                    human_review_required=False,
                    confidence=3.5,
                    rationale="Confianza imposible",
                )
            ),
            "invalid_output",
        ),
        (FakeOpenAIClient(error=openai_server_error()), "provider_error"),
    ],
)
def test_rn05_otras_fallas_de_openai(
    db: Session, actors: Actors, client: FakeOpenAIClient, reason: str
) -> None:
    ticket = new_ticket(db, actors.requester)

    drain(db, providers=fake_providers(classifier=OpenAIProvider(client, "gpt-falso")))

    db.refresh(ticket)
    assert ticket.priority is not None
    fallback = events_of(db, ticket, EventType.CLASSIFICATION_FALLBACK)
    assert fallback[0].safe_details_json["reason"] == reason


def test_rf21_clasificacion_con_openai_guarda_proveedor_y_modelo(
    db: Session, actors: Actors
) -> None:
    parsed = OpenAIClassificationOutput(
        category=Category.REDES,
        impact=Impact.AREA,
        urgency=Urgency.ALTA,
        human_review_required=False,
        confidence=0.88,
        rationale="Laboratorio sin conexión antes de clase.",
    )
    client = FakeOpenAIClient(parsed=parsed, model="gpt-falso-2026-10")
    ticket = new_ticket(db, actors.requester)

    drain(db, providers=fake_providers(classifier=OpenAIProvider(client, "gpt-falso")))

    classification = classification_repository.latest_for_ticket(db, ticket.id)
    assert classification.provider == ClassificationProvider.OPENAI
    assert classification.model_version == "gpt-falso-2026-10"
    assert str(classification.confidence) == "0.88"
    db.refresh(ticket)
    assert ticket.priority == Priority.CRITICA  # la matriz, no el modelo
    assert not events_of(db, ticket, EventType.CLASSIFICATION_FALLBACK)


def test_regla4_seguridad_sugerida_por_openai_pide_revision(db: Session, actors: Actors) -> None:
    parsed = OpenAIClassificationOutput(
        category=Category.SEGURIDAD,
        impact=Impact.INDIVIDUAL,
        urgency=Urgency.ALTA,
        human_review_required=False,  # aunque el modelo no lo pida, RN-04 lo exige
        confidence=0.97,
        rationale="Posible phishing.",
    )
    ticket = new_ticket(db, actors.requester)

    drain(
        db,
        providers=fake_providers(
            classifier=OpenAIProvider(FakeOpenAIClient(parsed=parsed), "gpt-falso")
        ),
    )

    db.refresh(ticket)
    assert ticket.review_required is True
    assert ticket.status == TicketStatus.PENDIENTE
