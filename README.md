# TRAZA

Sistema web para registrar, clasificar, priorizar y dar seguimiento a las solicitudes de soporte técnico del área de TI de la FISI (UNMSM). Un ticket solo se cierra cuando el solicitante confirma que el problema se resolvió.

Proyecto académico del curso Automatización y Control de Software (2026-II), grupo G3. La especificación completa está en [`docs/especificacion.md`](docs/especificacion.md) y las decisiones tomadas durante el desarrollo, en [`docs/decisiones.md`](docs/decisiones.md).

Para colaborar (ramas, commits, pull requests y migraciones), lee [`CONTRIBUTING.md`](CONTRIBUTING.md).

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
| `admin@traza.test` | Administrador (con WhatsApp simulado) |
| `tecnico1@traza.test`, `tecnico2@traza.test` | Técnico (con WhatsApp simulado) |
| `tecnico3@traza.test` | Técnico inactivo (no puede entrar ni recibe tickets) |
| `solicitante1@traza.test`, `solicitante2@traza.test` | Solicitante con WhatsApp |
| `solicitante3@traza.test` | Solicitante sin WhatsApp (confirma por la web) |

El seed es idempotente: si ya hay usuarios, no hace nada. Para empezar de cero: `alembic downgrade base && alembic upgrade head && python -m backend.scripts.seed`.

### 5. Arrancar el servidor

```bash
uvicorn backend.main:app --reload
```

Abre <http://localhost:8000> e inicia sesión con uno de los usuarios del seed.

### 6. Arrancar el worker

La clasificación, la asignación automática y el envío de mensajes no ocurren al registrar el ticket: los hace el worker a partir de la tabla `outbox_jobs`. En otra terminal:

```bash
python -m backend.workers.process_outbox          # bucle continuo
python -m backend.workers.process_outbox --once   # procesa lo pendiente y termina
```

Tras el seed, una pasada del worker clasifica TRZ-0001 a TRZ-0005 como en la sección 19 de la especificación y asigna los que no requieren revisión. TRZ-0005 (seguridad) queda pendiente de revisión del administrador.

## Demo del ciclo completo

1. Como `solicitante1`, registra una solicitud en **Nueva solicitud**.
2. Corre el worker: el ticket se clasifica y se asigna al técnico con menos carga.
3. Como el técnico asignado, abre el ticket, pulsa **Iniciar atención** y luego **Proponer solución**.
4. Corre el worker para "enviar" la pregunta de confirmación.
5. En **Simulador** (solo en desarrollo) aparece el chat del solicitante con los botones **Sí, se solucionó** / **No, continúa**. Con "No" el ticket se reabre y el técnico recibe el aviso; con "Sí" se cierra.
6. La **Bitácora** del detalle muestra cada paso con su actor y hora.

Ningún mensaje sale a la red: el canal es el simulador (`NOTIFICATION_PROVIDER=simulated`) y el clasificador es el mock (`CLASSIFIER_PROVIDER=mock`).

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
  integrations/    # adaptadores: clasificadores (mock, reglas) y WhatsApp simulado
  workers/         # worker de outbox_jobs
  templates/       # plantillas Jinja2
  static/          # CSS propio
  scripts/         # seed
migrations/        # Alembic
tests/             # unit, integration, acceptance
docs/              # especificación, decisiones
```

## Estado

- Fase 1 (Núcleo): login con roles, alta y listado de tickets con código único, evento `TICKET_CREATED` y trabajo en `outbox_jobs`.
- Fase 2 (Control): máquina de estados, asignación manual y automática, bitácora en el detalle, matriz de prioridad, clasificador mock y por reglas con fallback, worker de outbox con reintentos, notificaciones simuladas, confirmación por web y simulador.

Pendiente: GPT real y validación de clasificación por el admin (Fase 3), recordatorios, plazos y webhook de WhatsApp (Fase 4), panel de monitoreo (Fase 5).
