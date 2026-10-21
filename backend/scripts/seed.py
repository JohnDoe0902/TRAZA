"""Datos de prueba de la sección 19. Uso: python -m backend.scripts.seed

Todos los datos son sintéticos. Es idempotente: si ya hay usuarios, no hace nada.
"""

import sys
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.db import SessionLocal
from backend.core.security import hash_password
from backend.models import User
from backend.models.enums import Role
from backend.repositories import user_repository
from backend.schemas.ticket import TicketCreate
from backend.services import ticket_service


@dataclass(frozen=True)
class SeedUser:
    full_name: str
    email: str
    role: Role
    phone_e164: str | None = None
    whatsapp_opt_in: bool = False
    is_active: bool = True


# Teléfonos ficticios. Los técnicos activos y el admin aceptan WhatsApp para ver en el simulador
# los avisos que les corresponden (por ejemplo A8, "el problema continúa").
SEED_USERS = (
    SeedUser("Ana Torres", "admin@traza.test", Role.ADMIN, "+51900000100", True),
    SeedUser("Bruno Salas", "tecnico1@traza.test", Role.TECHNICIAN, "+51900000011", True),
    SeedUser("Carla Ríos", "tecnico2@traza.test", Role.TECHNICIAN, "+51900000012", True),
    SeedUser("Diego Paredes", "tecnico3@traza.test", Role.TECHNICIAN, is_active=False),
    SeedUser("Elena Quispe", "solicitante1@traza.test", Role.REQUESTER, "+51900000001", True),
    SeedUser("Fernando Huamán", "solicitante2@traza.test", Role.REQUESTER, "+51900000002", True),
    SeedUser("Gabriela Lozano", "solicitante3@traza.test", Role.REQUESTER),
)

# (correo del solicitante, título, descripción, ubicación). Se registran en este orden para que
# reciban los códigos TRZ-0001 a TRZ-0005 de la tabla de la sección 19.
SEED_TICKETS = (
    (
        "solicitante1@traza.test",
        "Laboratorio 3 sin internet",
        "Laboratorio de cómputo 3 sin internet, tengo clase en una hora",
        "Laboratorio de cómputo 3",
    ),
    (
        "solicitante2@traza.test",
        "Impresora sin tinta",
        "Impresora personal sin tinta",
        "Oficina de coordinación académica",
    ),
    (
        "solicitante3@traza.test",
        "Sin acceso a la plataforma interna",
        "No puedo entrar a la plataforma interna",
        None,
    ),
    (
        "solicitante1@traza.test",
        "Sin acceso al sistema de trámites",
        "Tres compañeros sin acceso al sistema de trámites",
        "Oficina de trámite documentario",
    ),
    (
        "solicitante2@traza.test",
        "Correo sospechoso",
        "Posible exposición de credenciales por un correo sospechoso",
        None,
    ),
)


def seed(db: Session, password: str) -> bool:
    """Crea usuarios y tickets. Devuelve False si la base ya tenía usuarios."""
    if user_repository.count(db) > 0:
        return False

    password_hash = hash_password(password)
    users: dict[str, User] = {}
    for data in SEED_USERS:
        users[data.email] = user_repository.add(
            db,
            User(
                full_name=data.full_name,
                email=data.email,
                password_hash=password_hash,
                phone_e164=data.phone_e164,
                role=data.role,
                whatsapp_opt_in=data.whatsapp_opt_in,
                is_active=data.is_active,
            ),
        )
    db.commit()

    for email, title, description, location in SEED_TICKETS:
        ticket_service.create_ticket(
            db,
            users[email],
            TicketCreate(title=title, description=description, location=location),
        )
    return True


def main() -> int:
    settings = get_settings()
    if settings.seed_password is None or not settings.seed_password.get_secret_value():
        print("Falta SEED_PASSWORD en .env; es la contraseña común de los usuarios de prueba.")
        return 1
    with SessionLocal() as db:
        created = seed(db, settings.seed_password.get_secret_value())
    if created:
        print(f"Seed listo: {len(SEED_USERS)} usuarios y {len(SEED_TICKETS)} tickets.")
    else:
        print("La base ya tiene usuarios; no se creó nada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
