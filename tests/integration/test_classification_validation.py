"""RN-04: el administrador valida o corrige la clasificación (CLASSIFICATION_VALIDATED)."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.core.errors import InvalidState, NotAuthorized
from backend.models import User
from backend.models.enums import (
    Category,
    ClassificationProvider,
    ConfirmationAnswer,
    EventType,
    Impact,
    JobType,
    Priority,
    TicketStatus,
    Urgency,
)
from backend.repositories import classification_repository
from backend.services import classification_service
from backend.workers.process_outbox import drain
from tests.helpers import (
    Actors,
    answer,
    events_of,
    fake_providers,
    jobs_of,
    new_ticket,
    pending_confirmation_ticket,
)

Login = Callable[[User], TestClient]
SECURITY = {
    "title": "Correo sospechoso",
    "description": "Posible exposición de credenciales por un correo sospechoso",
}


def _security_ticket_waiting_review(db: Session, actors: Actors):  # noqa: ANN202
    ticket = new_ticket(db, actors.requester, **SECURITY)
    drain(db, providers=fake_providers())
    db.refresh(ticket)
    assert ticket.review_required is True
    assert ticket.status == TicketStatus.PENDIENTE
    return ticket


def test_rn04_validar_libera_la_asignacion_automatica(db: Session, actors: Actors) -> None:
    ticket = _security_ticket_waiting_review(db, actors)

    classification_service.validate_classification(
        db,
        ticket,
        actors.admin,
        category=Category.SEGURIDAD,
        impact=Impact.EQUIPO,
        urgency=Urgency.ALTA,
    )

    assert ticket.review_required is False
    assert ticket.impact == Impact.EQUIPO
    assert ticket.priority == Priority.ALTA  # matriz: EQUIPO + ALTA
    latest = classification_repository.latest_for_ticket(db, ticket.id)
    assert latest.provider == ClassificationProvider.MANUAL
    assert latest.validated_by == actors.admin.id
    event = events_of(db, ticket, EventType.CLASSIFICATION_VALIDATED)[0]
    assert event.actor_id == actors.admin.id
    assert event.safe_details_json["previous"]["review_required"] is True
    assert event.safe_details_json["new"] == {
        "category": "SEGURIDAD",
        "impact": "EQUIPO",
        "urgency": "ALTA",
        "priority": "ALTA",
        "review_required": False,
    }
    assert JobType.AUTO_ASSIGN in [job.job_type for job in jobs_of(db, ticket)]

    drain(db, providers=fake_providers())
    db.refresh(ticket)
    assert ticket.status == TicketStatus.ASIGNADO


def test_corregir_clasificacion_recalcula_la_prioridad(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)  # el mock lo deja CRITICA
    drain(db, providers=fake_providers())
    db.refresh(ticket)

    classification_service.validate_classification(
        db,
        ticket,
        actors.admin,
        category=Category.HARDWARE,
        impact=Impact.INDIVIDUAL,
        urgency=Urgency.BAJA,
    )

    assert ticket.priority == Priority.BAJA
    assert ticket.status == TicketStatus.ASIGNADO  # ya estaba asignado: no se reasigna
    assert JobType.AUTO_ASSIGN not in [
        job.job_type for job in jobs_of(db, ticket) if job.status == "PENDING"
    ]


def test_validar_antes_de_la_clasificacion_automatica(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)

    classification_service.validate_classification(
        db,
        ticket,
        actors.admin,
        category=Category.REDES,
        impact=Impact.AREA,
        urgency=Urgency.MEDIA,
    )
    drain(db, providers=fake_providers())

    db.refresh(ticket)
    # El trabajo de clasificación posterior no pisa la decisión del admin.
    assert ticket.priority == Priority.ALTA
    assert not events_of(db, ticket, EventType.TICKET_CLASSIFIED)


def test_solo_el_admin_valida(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)
    for intruder in (actors.requester, actors.technician):
        with pytest.raises(NotAuthorized):
            classification_service.validate_classification(
                db,
                ticket,
                intruder,
                category=Category.OTROS,
                impact=Impact.INDIVIDUAL,
                urgency=Urgency.BAJA,
            )


def test_ticket_cerrado_no_se_reclasifica(db: Session, actors: Actors) -> None:
    ticket = pending_confirmation_ticket(db, actors)
    answer(db, ticket, actors.requester, ConfirmationAnswer.YES)

    with pytest.raises(InvalidState):
        classification_service.validate_classification(
            db,
            ticket,
            actors.admin,
            category=Category.OTROS,
            impact=Impact.INDIVIDUAL,
            urgency=Urgency.BAJA,
        )


def test_api_validacion(db: Session, actors: Actors, login: Login) -> None:
    ticket = _security_ticket_waiting_review(db, actors)
    url = f"/api/tickets/{ticket.public_code}/classification"
    body = {"category": "SEGURIDAD", "impact": "INDIVIDUAL", "urgency": "ALTA"}

    assert login(actors.technician).post(url, json=body).status_code == 403
    stale = login(actors.admin).post(url, json={**body, "version": ticket.version - 1})
    assert stale.status_code == 409
    response = login(actors.admin).post(url, json={**body, "version": ticket.version})
    assert response.status_code == 200, response.text
    assert response.json()["review_required"] is False
    assert response.json()["priority"] == "ALTA"
    invalid = login(actors.admin).post(url, json={**body, "category": "INVENTADA"})
    assert invalid.status_code == 422


def test_web_tarjeta_y_formulario_de_validacion(db: Session, actors: Actors, login: Login) -> None:
    ticket = _security_ticket_waiting_review(db, actors)
    admin = login(actors.admin)
    url = f"/tickets/{ticket.public_code}"

    page = admin.get(url).text
    assert "Validar y liberar asignación" in page
    assert "Sugerida por: mock" in page
    assert "Validar clasificación" not in login(actors.requester).get(url).text

    response = admin.post(
        f"{url}/clasificacion",
        data={
            "category": "SEGURIDAD",
            "impact": "INDIVIDUAL",
            "urgency": "ALTA",
            "version": ticket.version,
        },
    )
    assert "La prioridad se recalculó." in response.text  # aviso de la acción
    assert "Antes: Seguridad · individual · alta" in response.text  # entrada en la bitácora
    db.refresh(ticket)
    assert ticket.review_required is False


def test_filtro_requiere_revision(db: Session, actors: Actors, login: Login) -> None:
    pending = _security_ticket_waiting_review(db, actors)
    normal = new_ticket(db, actors.requester)
    drain(db, providers=fake_providers())

    page = login(actors.admin).get("/tickets", params={"revision": "1"}).text

    assert pending.public_code in page
    assert normal.public_code not in page
