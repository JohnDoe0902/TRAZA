# TRAZA

Sistema web para registrar, clasificar, priorizar y dar seguimiento a las solicitudes de soporte técnico del área de TI de la FISI (UNMSM). Un ticket solo se cierra cuando el solicitante confirma que el problema se resolvió.

Proyecto académico del curso Automatización y Control de Software (2026-II), grupo G3. La especificación completa está en [`docs/especificacion.md`](docs/especificacion.md) y las decisiones tomadas durante el desarrollo, en [`docs/decisiones.md`](docs/decisiones.md).

## Requisitos

- Python 3.13
- Docker y Docker Compose (para PostgreSQL 16)
- Git

## Instalación

### 1. Clonar y crear el archivo `.env`

```bash
git clone <url-del-repositorio> traza
cd traza
cp .env.example .env
```

Edita `.env` y completa como mínimo:

- `SECRET_KEY`: una cadena aleatoria larga. Puedes generarla con `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- `SEED_PASSWORD`: la contraseña común de los usuarios de prueba.

### 2. Levantar PostgreSQL

```bash
docker compose up -d db
```

El primer arranque crea dos bases: `traza` (desarrollo) y `traza_test` (pruebas). Si ya tenías el volumen de una versión anterior sin `traza_test`, créala con:

```bash
docker compose exec db psql -U traza -d traza -c "CREATE DATABASE traza_test OWNER traza;"
```

### 3. Entorno virtual y dependencias

Linux / macOS (bash):

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 4. Migraciones y datos de prueba

```bash
alembic upgrade head
python -m backend.scripts.seed
```

El seed crea 1 administrador, 2 técnicos activos, 1 técnico inactivo, 3 solicitantes y los tickets TRZ-0001 a TRZ-0005. Todos los usuarios usan la contraseña de `SEED_PASSWORD`:

| Correo | Rol |
|---|---|
| `admin@traza.test` | Administrador |
| `tecnico1@traza.test`, `tecnico2@traza.test` | Técnico |
| `tecnico3@traza.test` | Técnico inactivo (no puede entrar) |
| `solicitante1@traza.test`, `solicitante2@traza.test` | Solicitante con WhatsApp |
| `solicitante3@traza.test` | Solicitante sin WhatsApp |

El seed es idempotente: si ya hay usuarios, no hace nada. Para empezar de cero: `alembic downgrade base && alembic upgrade head && python -m backend.scripts.seed`.

### 5. Arrancar el servidor

```bash
uvicorn backend.main:app --reload
```

Abre <http://localhost:8000> e inicia sesión con uno de los usuarios del seed.

## Pruebas y calidad

Las pruebas usan la base `traza_test` (variable `TEST_DATABASE_URL`) y aplican las migraciones automáticamente al empezar. Cada prueba corre en una transacción que se revierte al final. Nunca llaman a OpenAI ni a WhatsApp reales.

```bash
pytest                  # todas las pruebas
pytest tests/unit -q    # solo unitarias
ruff check .            # lint
ruff format .           # formato
```

## Estructura

```text
backend/
  main.py          # crea la app, monta routers, plantillas y estáticos
  api/             # routers JSON y páginas web
  core/            # configuración, base de datos, seguridad, permisos, errores
  models/          # modelos SQLAlchemy y enums de dominio
  schemas/         # esquemas Pydantic
  repositories/    # acceso a datos
  services/        # lógica de negocio
  templates/       # plantillas Jinja2
  static/          # CSS propio
  scripts/         # seed
migrations/        # Alembic
tests/             # unit, integration, acceptance
docs/              # especificación, decisiones
```

## Estado

Fase 1 (Núcleo) de la sección 18 de la especificación: login con roles, alta y listado de tickets con código único, evento `TICKET_CREATED` y trabajo en `outbox_jobs`. La clasificación, asignación, notificaciones y confirmación llegan en las fases siguientes.
