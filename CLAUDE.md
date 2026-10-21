# TRAZA — instrucciones para Claude Code

TRAZA es un sistema web que automatiza el registro, la clasificación, la priorización y el seguimiento de solicitudes de soporte técnico del área de TI de la FISI (UNMSM). Un ticket solo se cierra cuando el solicitante confirma que el problema se resolvió.

Proyecto académico del curso Automatización y Control de Software (2026-II), grupo G3, 6 integrantes. Entrega final en la semana 16.

La especificación completa (requisitos, reglas, estados, modelo de datos, API, integraciones y casos de prueba) está en `docs/especificacion.md`. Léela, en la sección que corresponda, antes de implementar cualquier módulo. Si algo de este archivo choca con la especificación, manda la especificación y avisa del conflicto.

## Stack

- Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2.0 (estilo síncrono), Alembic.
- PostgreSQL 16 (servicio `db` en `docker-compose.yml`). Las pruebas usan una base aparte, `traza_test`.
- Interfaz: plantillas Jinja2 + Bootstrap 5 servidas por FastAPI. Sin React ni build de frontend.
- Sesión web con cookie firmada; contraseñas con hash argon2id.
- Pruebas: pytest + HTTPX (TestClient).
- IA: OpenAI API (GPT) detrás de un adaptador. Mensajería: WhatsApp Cloud API detrás de un adaptador, con simulador.
- Sin Redis ni Celery: la cola de trabajos es la tabla `outbox_jobs` y un worker propio.

## Comandos

Mantén esta sección al día cuando cambien.

```bash
docker compose up -d db                        # levantar PostgreSQL
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head                           # aplicar migraciones
python -m backend.scripts.seed                 # usuarios y tickets de prueba
uvicorn backend.main:app --reload              # servidor en http://localhost:8000
python -m backend.workers.process_outbox       # worker de la cola
python -m backend.workers.process_outbox --once  # procesa lo pendiente y termina
python -m backend.scripts.try_classifier       # prueba manual del clasificador configurado
pytest                                         # todas las pruebas
pytest tests/unit -q                           # solo unitarias
ruff check . && ruff format .                  # lint y formato
```

## Estructura

```text
backend/
  main.py              # crea la app, monta routers, plantillas y estáticos
  api/                 # routers: auth, tickets, dashboard, whatsapp_webhook, web (páginas)
  core/                # config (pydantic-settings), db, security, permissions
  models/              # modelos SQLAlchemy
  schemas/             # esquemas Pydantic de entrada y salida
  repositories/        # acceso a datos, sin lógica de negocio
  services/            # lógica de negocio: ticket, priority_rules, assignment,
                       # classification, message, notification, confirmation, audit
  integrations/        # adaptadores: openai_provider, rule_provider, mock_provider,
                       # whatsapp_provider, simulated_whatsapp
  workers/             # process_outbox.py
  templates/ static/   # Jinja2 y CSS/JS propios
  scripts/             # seed y utilidades
migrations/            # Alembic
tests/unit/ tests/integration/ tests/acceptance/
docs/                  # especificacion.md, plan_pruebas.md, decisiones.md
```

Flujo de dependencias: `api` → `services` → `repositories` → `models`. Los routers no tocan la base de datos directamente. Los servicios no importan clientes HTTP externos: usan los adaptadores de `integrations/` a través de una interfaz (Protocol).

## Reglas que no se rompen

Estas reglas son el corazón del proyecto y el profesor las va a evaluar. Cada una debe tener al menos una prueba.

1. **Solo el usuario cierra.** El técnico propone una solución (`RESOLUTION_PROPOSED`) y el ticket pasa a `PENDIENTE_CONFIRMACION`. Solo una respuesta Sí del solicitante lo lleva a `CERRADO`. El silencio nunca cierra.
2. **Transiciones válidas únicamente.** Toda transición pasa por una única función del servicio de tickets que valida contra la tabla de transiciones de la especificación. Una transición inválida lanza un error de dominio y no cambia nada.
3. **Todo cambio deja evento.** Cada cambio de estado, asignación, clasificación, notificación y confirmación agrega una fila a `ticket_events` en la misma transacción que el cambio. La tabla es solo de inserción: la aplicación nunca actualiza ni borra eventos.
4. **La IA sugiere, las reglas deciden.** GPT solo sugiere categoría, impacto y urgencia. La prioridad final sale de la matriz de `priority_rules.py`. Un incidente de seguridad siempre pide revisión humana.
5. **Nada externo bloquea el registro.** Crear un ticket guarda ticket + evento + trabajo en `outbox_jobs` en una transacción y responde. GPT y WhatsApp se llaman después, desde el worker.
6. **Fallback siempre.** Si GPT falla o devuelve algo que no pasa el esquema, se clasifica con `rule_provider` y se registra `CLASSIFICATION_FALLBACK`. Si la redacción falla, se usa una plantilla fija.
7. **Idempotencia.** Una misma respuesta de confirmación o un mismo webhook procesado dos veces produce un solo cambio lógico (clave única en `confirmations.provider_event_id` y en `notifications.idempotency_key`).
8. **Permisos por objeto.** Un solicitante solo ve sus tickets; un técnico, los asignados; el administrador, todos. Acceso indebido = 403, nunca datos de otro.
9. **Enviado no es entregado.** El estado de una notificación solo avanza con evidencia del proveedor o del simulador.

## Convenciones

- Código, nombres de variables, funciones, clases y tablas en inglés. Textos de la interfaz, mensajes al usuario y documentación en español.
- Valores de estado tal como en la especificación: `PENDIENTE`, `ASIGNADO`, `EN_PROCESO`, `PENDIENTE_CONFIRMACION`, `CERRADO`, `REABIERTO`. Tipos de evento en inglés y mayúsculas (`TICKET_CREATED`).
- Enums de dominio como `enum.StrEnum` en un solo módulo (`backend/models/enums.py`).
- Fechas en UTC en la base de datos (`timestamptz`); se muestran en hora de Lima (America/Lima).
- Código público de ticket: `TRZ-0001`, generado con una secuencia de PostgreSQL, nunca con `max()+1`.
- Configuración solo por variables de entorno leídas en `core/config.py`. Nunca escribas claves en el código. `.env` va en `.gitignore`; `.env.example` lleva las variables sin valores reales.
- Errores de dominio como excepciones propias (`InvalidTransition`, `NotAuthorized`, etc.) traducidas a HTTP en un solo manejador.
- Logs sin contraseñas, tokens, mensajes completos ni teléfonos sin enmascarar.
- Tipado en todas las funciones públicas. Funciones cortas, sin lógica de negocio en plantillas.

## Pruebas

- Cada requisito imprescindible (RF-01 a RF-18) y cada regla de arriba tiene al menos una prueba. Nombra las pruebas con el caso que cubren cuando exista: `test_cp08_pendiente_a_cerrado_rechazado`.
- Las pruebas nunca llaman a OpenAI ni a WhatsApp reales: usan `mock_provider` y `simulated_whatsapp`.
- Cada prueba corre en una transacción que se revierte al final.
- Antes de dar una tarea por terminada, corre `pytest` y `ruff check .` y reporta el resultado real.

## Forma de trabajar

- Trabaja por fases, en el orden de la sección "Plan de implementación" de la especificación. No adelantes WhatsApp real ni la API real de GPT antes de que el núcleo funcione con los simuladores.
- Antes de cambios grandes, propone un plan corto y espera el visto bueno.
- Cambios pequeños y enfocados; un commit por unidad lógica, con mensaje en español en imperativo ("Agrega validación de transiciones").
- Ramas por módulo (`feature/tickets`, `feature/audit`). No hagas push ni merge a `main` sin que te lo pidan.
- Si una decisión no está en la especificación, elige la opción más simple, anótala en `docs/decisiones.md` y avísame.
- No inventes resultados de pruebas ni métricas: el informe final usa solo resultados reales.
