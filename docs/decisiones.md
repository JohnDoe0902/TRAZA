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

### D-41 · Telegram como canal y Gemini como IA
El equipo acordó usar un bot de Telegram para avisos y confirmación Sí/No, en lugar de WhatsApp Cloud API (exige RUC y cobra) y del correo de la guía. Para la IA se usará la API gratuita de Gemini en lugar de GPT. Telegram será un adaptador más (`NotificationProvider`), con el simulador como opción por defecto y en las pruebas. Pendiente: actualizar `docs/especificacion.md` y `CLAUDE.md` con acuerdo de los tres.

### D-42 · Cómo se mide el plazo de primera atención
El plazo (tabla 7.2) corre desde `tickets.created_at`, en minutos corridos, y solo para tickets que ya tienen prioridad. Se cumple con la primera atención (`first_response_at`, paso a `EN_PROCESO`). `SLA_BREACHED` se registra una sola vez por ticket (`sla_breached_at`); si el administrador cambia la prioridad después, no se vuelve a registrar. CRITICA y ALTA → `ADMIN_ALERT`. MEDIA y BAJA → recordatorio al técnico; si todavía no hay técnico, `ADMIN_ALERT`.

### D-43 · Recordatorio al técnico sin mensaje por ahora
No existe una plantilla de "recordatorio al técnico" y agregar un tipo de mensaje cambia el CHECK de `notifications.message_type` (migración de A). Mientras tanto, el recordatorio queda como `SLA_BREACHED` con `action = technician_reminder` y el `technician_id`, visible en la línea de tiempo. Cuando A agregue la plantilla A9, se enviará también el mensaje.

### D-44 · Recordatorio de confirmación una vez por ciclo
El ciclo vigente es `reopen_count + 1`, igual que en `confirmations.confirmation_round`. El recordatorio sale si pasaron `REMINDER_AFTER_MINUTES` desde el `CONFIRMATION_REQUESTED` de ese ciclo, no hay respuesta y no se registró ya un `CONFIRMATION_REMINDER` con ese `confirmation_round`. Envía A7 al solicitante y registra `CONFIRMATION_REMINDER` y `ADMIN_ALERT`. Nunca cambia el estado (regla 1). Cada ticket se revisa con su fila bloqueada (`FOR UPDATE SKIP LOCKED`), así dos workers no duplican avisos; si la revisión falla, el worker lo registra y sigue con la cola.

### D-45 · /health en dos partes
`/health` ahora lo arma `services/health_service.py` (el router ya no llama al repositorio directo). Devuelve el estado de la base y cuántos trabajos de `outbox_jobs` están `PENDING` y `FAILED`. Responde 200 si la base contesta y 503 con `"status": "degraded"` si no; en ese caso no muestra cifras de la cola. El latido del worker se suma cuando A cree la tabla `worker_heartbeats`.

### D-46 · Migración 0003 escrita por B, pendiente del visto bueno de A
La escribió el integrante B para no frenar su frente y A la revisa en el PR. Agrega a `users` el `telegram_chat_id` (BIGINT, único) y un token de vinculación de un solo uso con vencimiento (`telegram_link_token`, `telegram_link_expires_at`). Crea `worker_heartbeats` con una fila por worker (`worker_id` = equipo:pid). Amplía los CHECK para aceptar `TELEGRAM` en `notifications.channel` y `confirmations.source`, y `A9` en `notifications.message_type`. Plantilla A9: "Recordatorio: {codigo} superó su plazo de primera atención. Revísalo en tu bandeja." `whatsapp_opt_in` se mantiene por ahora; se decide su reemplazo al conectar Telegram.

### D-47 · Latido del worker en /health
En cada ciclo el worker hace un upsert en `worker_heartbeats` con su `worker_id` (equipo:pid). `/health` toma el latido más reciente: hasta 60 s → `ok`, más viejo → `down`, sin filas → `never_seen`. El código HTTP depende solo de la base (200 o 503): con el worker caído la web sigue registrando tickets (regla 5), así que responde 200 con `"status": "degraded"`. Si el latido falla, el worker lo registra en el log y sigue con la cola.

### D-48 · Canal de Telegram
`NOTIFICATION_PROVIDER=telegram` usa `TelegramChannel`, que cumple el mismo `NotificationProvider` que el simulador. La pregunta A3 lleva dos botones (`c:<id de notificación>:YES|NO`, bajo el límite de 64 bytes de Telegram). El estado queda `SENT` porque Telegram no avisa a los bots de la lectura (regla 9). Con Telegram solo se encola un aviso si el destinatario tiene `telegram_chat_id`; con el simulador se sigue usando `whatsapp_opt_in`. El registro de `httpx2` se sube a WARNING porque escribe la URL completa, y en Telegram la URL lleva el token.

### D-49 · Vinculación con /start y token de un solo uso
Un bot no puede escribirle primero a nadie. En `/telegram` la persona pide un enlace `t.me/<bot>?start=<token>` (32 caracteres, vence a los `TELEGRAM_LINK_MINUTES`). Al pulsar Iniciar llega `/start <token>`, se guarda el `chat_id` y se borra el token. Un enlace nuevo invalida el anterior. Un chat no puede vincularse a dos cuentas (único en la base). El bot solo atiende chats privados.

### D-50 · Respuestas por polling y no por webhook
`python -m backend.workers.telegram_bot` pide los mensajes con `getUpdates` y espera larga (25 s). Funciona en cualquier PC sin HTTPS ni túnel, que es lo que pide la demo. Va en un proceso aparte del worker de la cola. Cada botón pulsado trae un id propio de Telegram que se guarda como `provider_event_id = tg-<id>`, así el mismo update repetido produce un solo cambio (CP-14). Solo vale el botón de la última A3 del ticket: uno de una ronda anterior responde "ya no está vigente" sin tocar la ronda nueva. Si un update falla, se registra y se sigue con el siguiente. `--once` procesa lo pendiente y confirma el offset antes de terminar.

### D-51 · El recordatorio al técnico ya se envía (actualiza D-43)
Con la plantilla A9 de la migración 0003, un plazo vencido de prioridad MEDIA o BAJA con técnico asignado también encola el mensaje A9 al técnico, además del `SLA_BREACHED`. Si el técnico no puede recibir por el canal activo (por ejemplo, no vinculó Telegram), queda solo el evento.

### D-52 · Diseño de los avisos en Telegram
El texto base de cada aviso sigue siendo la plantilla de la sección 16 (la usan el simulador, el validador y la auditoría). Solo el canal de Telegram le da presentación en `integrations/telegram_format.py`: título con emoji según el tipo, ficha con ticket, asunto y estado, el texto base con el código en negrita, una indicación si hace falta (por ejemplo en A3) y un pie. Va en HTML de Telegram y todo lo que viene del usuario se escapa. Como el estado va en la ficha, se quita la frase "Estado: X." del texto base solo en Telegram. Las respuestas propias del bot (vincular, ayuda, botones) también se ordenaron.

### D-53 · A6 a los administradores cuando un aviso falla del todo
Cuando un `SEND_NOTIFICATION` agota sus intentos, la notificación queda `FAILED` y se encola A6 ("No se pudo enviar el mensaje del ticket {codigo}. Intento {n}.") para cada administrador activo, en la misma transacción. Si lo que falló ya era un A6 no se manda otro, para que una caída del canal no genere avisos sin fin. El ticket sigue su curso normal (CP-10). Las pruebas de la guía quedan con su nombre: `test_cp10_...` y `test_cp11_...`.

### D-54 · Plazos y recordatorios filtrados en la base
`run_checks` corre cada 5 s. Antes traía todos los tickets en espera y leía la bitácora de cada uno. Ahora la base devuelve solo los vencidos: `list_sla_due` arma un corte por prioridad (`now - plazo`) y `list_reminder_due` usa `EXISTS` sobre `ticket_events` (con el índice `ticket_id, created_at` que ya existe) y `confirmations` para la ronda actual. Si nada venció son 2 consultas, sin importar cuántos tickets haya; una prueba lo vigila. Cada ticket vencido se sigue revisando con su fila bloqueada antes de actuar.

### D-55 · Código QR para vincular y nombre del bot desde el token
La página `/telegram` muestra el enlace de vinculación como código QR para escanearlo con el celular, aunque la web esté abierta en otra PC (por ejemplo, la laptop de la demo). El QR lo dibuja `segno` en el mismo servidor, como SVG y sin servicios externos, con corrección de errores alta porque lleva el logo al centro. El nombre del bot ya no depende de escribirlo bien en el `.env`: si hay `TELEGRAM_BOT_TOKEN`, se pregunta a Telegram con `getMe` una vez por proceso, y solo si Telegram no responde se usa `TELEGRAM_BOT_USERNAME`. Así cualquier PC funciona con su propio bot poniendo solo su token. El token del bot nunca va en el QR: el QR solo lleva el código de vinculación de un solo uso.
