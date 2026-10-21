# Decisiones de implementación

Decisiones que no estaban en `docs/especificacion.md`. Para cada una se eligió la opción más simple.

## Fase 1 — Núcleo

### D-01 · Control de versiones
El repositorio se inicializó con un commit en `main` (especificación y `CLAUDE.md`). El trabajo de la Fase 1 va en la rama `feature/nucleo`.

### D-02 · `created_at` en todas las tablas
La sección 12 dice que todas las tablas tienen `created_at`, pero `assignments` y `confirmations` solo listan `assigned_at` y `responded_at`. Se dejan ambas columnas: `created_at` (momento de inserción) y la fecha de negocio.

### D-03 · `ticket_events` protegida también en la base
Además de que la aplicación nunca actualiza ni borra eventos, la migración crea un trigger (`ticket_events_append_only`) que rechaza cualquier `UPDATE` o `DELETE` sobre la tabla. Así la regla 3 se cumple aunque alguien escriba SQL a mano.

### D-04 · Generación del código público
Se obtiene `nextval('ticket_code_seq')` y se formatea en Python con `f"TRZ-{n:04d}"`. No se usa `lpad` de PostgreSQL porque trunca los números de más de 4 dígitos (TRZ-10000 se convertiría en TRZ-1000).

### D-05 · Sesión web
`SessionMiddleware` de Starlette: cookie firmada con `SECRET_KEY`, `httponly`, `samesite=lax`, duración 8 horas. Solo guarda `user_id`; el usuario se vuelve a leer de la base en cada petición, de modo que un usuario desactivado pierde el acceso de inmediato. La cookie es `https_only` fuera de `APP_ENV=development`/`test`.

### D-06 · Sin sesión
Las rutas `/api/*` responden 401 sin sesión válida. Las páginas web redirigen a `/login`.

### D-07 · CSRF pendiente
En la Fase 1 no hay token CSRF en los formularios; la protección se apoya en `SameSite=Lax`. Queda pendiente para una fase posterior.

### D-08 · Ubicación de los errores de dominio
`backend/core/errors.py` define `DomainError` y sus subclases, más un único manejador que las traduce a HTTP (`NotAuthenticated` 401, `NotAuthorized` 403, `NotFound` 404, `InvalidTransition` y `ConcurrencyConflict` 409).

### D-09 · Trabajos del alta
El alta crea los trabajos `CLASSIFY_TICKET` y, si el solicitante aceptó WhatsApp, `SEND_NOTIFICATION` con `message_type = A1`. La fila de `notifications` la creará el worker al procesar el trabajo (Fase 2), no el alta.

### D-10 · Seed
Los tickets del seed se crean con el mismo `ticket_service` que usa la web, así que quedan en `PENDIENTE` y sin clasificar; la clasificación esperada de la sección 19 se obtendrá cuando el worker de la Fase 2 los procese. El seed no hace nada si ya existen usuarios.

### D-11 · Ticket inexistente
`GET /api/tickets/{code}` con un código que no existe responde 404. Responder 403 en ese caso no aporta privacidad adicional porque los códigos son secuenciales.

### D-12 · Usuario técnico de prueba inactivo
`tecnico3@traza.test` es el técnico inactivo del seed. No puede iniciar sesión (RF-01).

### D-13 · Tipos de mensaje A1–A8
La sección 12 dice que `notifications.message_type` va de A1 a A6, pero la sección 16 define también A7 (recordatorio) y A8 (aviso al técnico), que se envían como notificaciones. El CHECK admite A1–A8.

### D-14 · `httpx2` en lugar de `httpx`
Starlette 1.9 marca como obsoleto su `TestClient` con `httpx` y pide `httpx2` (la continuación de HTTPX). `requirements.txt` instala `httpx2`.

### D-15 · Correo sin `EmailStr`
`email-validator` rechaza el dominio reservado `.test` que exige la sección 19 para los datos de prueba. El login valida el correo como texto (3–254 caracteres) y lo compara sin distinguir mayúsculas.

### D-16 · Regla N818 de ruff desactivada
Los nombres `InvalidTransition`, `NotAuthorized`, etc. vienen de `CLAUDE.md`; ruff pediría el sufijo `Error`.

### D-17 · Mensajes de validación
El formulario web muestra los errores en español junto a cada campo. La API JSON devuelve el 422 estándar de FastAPI (detalle por campo, mensajes en inglés); traducirlos queda pendiente.

### D-18 · Base de pruebas
Cada corrida de `pytest` hace `alembic downgrade base` y `upgrade head` sobre `traza_test`, lo que además prueba la migración en ambos sentidos. Como protección, las pruebas se niegan a correr si `TEST_DATABASE_URL` apunta a la misma base que `DATABASE_URL`.

### D-19 · CP-04 sin datos confirmados
La prueba de altas concurrentes usa varias conexiones, cada una con su transacción, y las revierte al final. Así cumple "cada prueba se revierte" y aun así ejercita `nextval` y el índice único entre conexiones reales. Se comprobó que falla si el código se genera con `max()+1`.

## Fase 2 — Control

### D-20 · La notificación se crea al encolar (reemplaza D-09)
Al encolar un mensaje se crea en la misma transacción la fila de `notifications` (estado `PENDING`, cuerpo de la plantilla) y el trabajo `SEND_NOTIFICATION` con su `notification_id`. Así `CONFIRMATION_REQUESTED` guarda el id de la notificación (sección 10). La clave de idempotencia es `ticket:tipo:destinatario:correlation_id`.

### D-21 · Solo destinatarios con opt-in
Se notifica únicamente a usuarios con `whatsapp_opt_in` (RN-14), también por el simulador. En el seed, los técnicos activos y el admin aceptan WhatsApp con teléfonos ficticios para que el aviso A8 se vea en el simulador. Quien no aceptó confirma por la web.

### D-22 · Reasignación desde EN_PROCESO
Devuelve el ticket a `ASIGNADO` y registra `TICKET_ASSIGNED` y `TICKET_STATUS_CHANGED`. La tabla 8.2 solo menciona el primero, pero la regla 3 exige un evento por cada cambio de estado. `ASIGNADO → ASIGNADO` solo registra `TICKET_ASSIGNED`. La reapertura usa `TICKET_REOPENED` (con estados anterior y nuevo) como evento del cambio, como indica la tabla.

### D-23 · Cierre excepcional del administrador no implementado
Es deseable (D) y la sección 21 lo deja pendiente.

### D-24 · Detalles de `RuleProvider`
Analiza solo título y descripción (la ubicación "Oficina…" volvería AREA cualquier falla personal). Su confianza es nula, así que no dispara RN-04 por sí sola. Se agregaron palabras para `SOFTWARE` y "sospechoso" para `SEGURIDAD`; la seguridad se evalúa primero.

### D-25 · Simulador
`/simulador` solo existe con `APP_ENV` development o test. El admin ve los chats de todos los usuarios con WhatsApp; los demás, solo el suyo. La respuesta queda a nombre del destinatario del mensaje con `source = SIMULATOR` y `provider_event_id = sim-<notificación>-<respuesta>`, de modo que pulsar dos veces el mismo botón es un duplicado.

### D-26 · Mecanismo de fallback listo antes de OpenAI
`classification_service` ya cae a reglas ante excepción, timeout o salida inválida (probado con un proveedor falso). CP-06 se cierra formalmente en la Fase 3 con `OpenAIProvider`, que deberá convertir sus timeouts en `TimeoutError`.

### D-27 · `outbox_jobs.started_at`
Migración 0002. Marca cuándo el worker tomó el trabajo; con ella se detectan los `RUNNING` abandonados por más de 10 minutos (CP-18).

### D-28 · Versión del ticket en las operaciones
Cada operación compara la versión enviada por el cliente una sola vez, al inicio. Además, SQLAlchemy usa `tickets.version` como `version_id_col`: si otra transacción cambió el ticket entre la lectura y la escritura, el UPDATE falla y se responde 409.

### D-29 · Respuestas repetidas o tardías
Se distinguen en `DUPLICATE_ANSWER_IGNORED.reason`: `duplicate` (mismo `provider_event_id` o choque con otra respuesta del mismo ciclo) y `not_pending` (el ticket ya no espera confirmación). La API web responde 200 con `result = IGNORED`.

### D-30 · Ciclo de confirmación
`confirmation_round = reopen_count + 1`: la primera solución es la ronda 1 y cada reapertura abre una ronda nueva.

## Fase 3 — IA y mensajes

### D-31 · SDK oficial de OpenAI con salida estructurada
`openai==3.35.1`, API de Responses (`client.responses.parse`) con un modelo Pydantic propio (`OpenAIClassificationOutput`) que el SDK convierte en JSON Schema estricto: todos los campos obligatorios, sin campos extra y sin `priority`. La respuesta se vuelve a validar contra el esquema 13.1 (`ClassificationResult`). Se envía con `store=False` y un límite de 400 tokens de salida.

### D-32 · Sin reintentos dentro del cliente
`max_retries=0` y `timeout=OPENAI_TIMEOUT_SECONDS`. Si OpenAI falla, el respaldo por reglas es inmediato (RN-05); reintentar dentro del cliente solo alargaría la espera del worker.

### D-33 · Mapeo de fallas al motivo del fallback
`APITimeoutError` → `timeout`; respuesta vacía o rechazada (`ProviderOutputError`) o fuera de esquema (`ValidationError`) → `invalid_output`; cualquier otro error (HTTP, conexión, autenticación) → `provider_error`.

### D-34 · Datos personales enmascarados antes de enviar a GPT
Además de no enviar datos del usuario (RN-14), el texto que escribe el solicitante pasa por `redact_personal_data`: correos → `[correo]` y secuencias de 7 o más dígitos (teléfonos, DNI) → `[número]`. Los nombres propios escritos en la descripción no se pueden detectar con reglas simples; queda como riesgo conocido.

### D-35 · GPT nunca recibe nombres (conflicto 13.2 vs RN-14)
La sección 13.2 permite enviar el nombre de pila "si está autorizado"; RN-14 prohíbe enviar nombres a GPT. Se aplica la regla más estricta: el redactor recibe el propósito, el código, el estado y el mensaje base **sin** nombre. El saludo con nombre queda solo en las plantillas.

### D-36 · OpenAI mal configurado no arranca
Con `CLASSIFIER_PROVIDER=openai` o `MESSAGE_COMPOSER=openai` y sin `OPENAI_API_KEY` u `OPENAI_MODEL`, el worker termina con código 2 y un mensaje claro. No se cambia a reglas en silencio, para que un error de configuración no pase desapercibido en la demo.

### D-37 · Redacción en el worker, solo en el primer intento
El cuerpo guardado al encolar es la plantilla (sin llamadas externas en la transacción). Con `MESSAGE_COMPOSER=openai`, el worker redacta justo antes del primer envío; si el redactor falla o el texto no pasa `validate_message`, se envía la plantilla. Un reintento reenvía el texto ya guardado sin volver a llamar a GPT. `NOTIFICATION_SENT` registra `composer` y, si hubo respaldo, `composer_fallback` con el motivo.

### D-38 · Reglas del validador de mensajes (13.2)
Rechaza: vacío, más de 500 caracteres, sin el código del ticket, las palabras "cerrado/a" o "resuelto/a" si el ticket no está `CERRADO` (sin distinguir mayúsculas ni tildes), URLs (`http`, `www.` o dominios como `.com`, `.pe`, `.edu`), correos y secuencias de 7 o más dígitos. Las 8 plantillas pasan el validador en su estado natural.

### D-39 · Validación de la clasificación por el administrador
`POST /api/tickets/{code}/classification` (y el formulario del detalle) crea una fila `classifications` con `provider = manual` y `validated_by`, recalcula la prioridad con la matriz, deja `review_required = false` y registra `CLASSIFICATION_VALIDATED` con los valores anteriores y nuevos. Si el ticket sigue `PENDIENTE` y sin técnico, encola `AUTO_ASSIGN`. Se permite en cualquier estado salvo `CERRADO` (409, error `InvalidState`). Si el admin clasifica antes que el worker, el trabajo de clasificación pendiente ya no hace nada.

### D-40 · Prueba manual con la API real
`python -m backend.scripts.try_classifier` clasifica los 5 textos del seed con el proveedor configurado y los compara con la sección 19. Es la evidencia de la demo con GPT real; nunca corre en `pytest`, y `tests/conftest.py` bloquea cualquier llamada real a la API de OpenAI.
