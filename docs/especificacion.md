# TRAZA — Especificación técnica para el desarrollo

Versión 1.0 · 19 de octubre de 2026 · Grupo G3 · Automatización y Control de Software 2026-II

Este documento es la fuente de verdad para implementar TRAZA. Resume el documento maestro del proyecto (v1.2) y el plan consolidado, y fija las decisiones técnicas que faltaban para poder programar. Si algo no está aquí, se elige la opción más simple y se anota en `docs/decisiones.md`.

---

## 1. Contexto y objetivo

**Problema.** En el área de soporte de TI de la FISI (UNMSM), las fallas de laboratorios y oficinas se reportan por llamadas o mensajes personales. No hay código único, la prioridad la decide cada técnico, no queda historial y los casos se dan por resueltos sin que el usuario confirme. Este escenario es una hipótesis de trabajo, no una medición.

**Objetivo general.** Automatizar el registro, la clasificación, la priorización, el seguimiento y la comunicación de solicitudes de soporte, con trazabilidad de cada acción y verificación de la resolución mediante la confirmación del usuario.

**Idea central.** "Resuelto" es una acción del técnico; "cerrado" exige que el solicitante confirme. Todo cambio queda en una bitácora reconstruible.

**Entregas.** Parte I (semana 8): diseño y prototipo, ya entregada. Parte II (semana 16): MVP funcionando, pruebas con evidencia real e informe final.

---

## 2. Actores, roles y permisos

| Rol (`users.role`) | Quién es | Puede | No puede |
|---|---|---|---|
| `REQUESTER` (solicitante) | Docente, administrativo o encargado de laboratorio | Crear tickets, ver los suyos y su historial, confirmar o rechazar la solución | Ver tickets ajenos, cambiar prioridad, asignar |
| `TECHNICIAN` (técnico) | Personal de soporte | Ver tickets asignados, iniciar atención, registrar diagnóstico, proponer solución | Ver o actuar sobre tickets no asignados, cerrar, borrar historial |
| `ADMIN` (administrador) | Supervisor del área | Ver todo, asignar y reasignar, validar o corregir la clasificación, ver monitoreo y auditoría | Borrar o editar eventos, confirmar en nombre del solicitante |
| Sistema | Worker y procesos automáticos | Clasificar, asignar por reglas, notificar, recordar, alertar | Saltarse validaciones de estado o permisos |
| Servicios externos | OpenAI (GPT) y WhatsApp | Sugerir clasificación, redactar mensajes, transportar mensajes | Ser fuente de verdad del estado del ticket |

Permisos por objeto: toda consulta de un ticket comprueba que el usuario sea su solicitante, su técnico asignado o un administrador. Si no, responde 403 (no 404 con datos ni 200 vacío).

---

## 3. Alcance del MVP

**Incluido:** inicio de sesión con roles; registro web con validación y código único; clasificación con GPT o reglas; prioridad por matriz; asignación manual y automática básica; estados con transiciones validadas; bitácora de auditoría; diagnóstico y solución propuesta; notificaciones (simuladas desde el inicio); confirmación Sí / No con cierre o reapertura; recordatorio sin respuesta; panel de indicadores; pruebas automatizadas.

**Fuera del MVP:** tickets creados desde WhatsApp, chatbot, app móvil nativa, análisis de imágenes o audio, calendarios laborales reales, ERP, microservicios, una IA que cierre casos o cambie prioridades sin control.

**Supuestos:** datos sintéticos en todo momento; los plazos son parámetros de demostración, no políticas de la FISI; GPT y WhatsApp reales dependen de credenciales y costos, y el sistema siempre funciona con sus simuladores.

---

## 4. Requisitos funcionales

Prioridad: **M** imprescindible para la semana 16 · **D** deseable si hay tiempo · **F** fase futura (no implementar).

| ID | P | Requisito | Criterio de aceptación |
|---|---|---|---|
| RF-01 | M | Autenticar usuarios con rol | Credenciales válidas entran; inválidas o usuario inactivo, no |
| RF-02 | M | Crear tickets con validación de campos | Ticket válido se guarda; inválido devuelve error y no guarda nada |
| RF-03 | M | Generar código único (`TRZ-0001`) | Sin duplicados, incluso con altas concurrentes |
| RF-04 | M | Listar tickets según rol | Cada rol ve solo lo que le corresponde |
| RF-05 | M | Clasificar por categoría, urgencia e impacto | Se guarda una fila en `classifications` |
| RF-06 | M | Calcular prioridad con la matriz | Prioridad igual a la de la tabla 7.1 |
| RF-07 | M | Seguir con reglas si la IA falla | El ticket se clasifica igual; evento `CLASSIFICATION_FALLBACK` |
| RF-08 | M | Asignar o reasignar responsable | Fila en `assignments` y evento `TICKET_ASSIGNED` |
| RF-09 | M | Cambiar de estado solo según transiciones válidas | Transición inválida rechazada, estado intacto |
| RF-10 | M | Registrar automáticamente eventos de auditoría | Cada cambio tiene su evento en la misma transacción |
| RF-11 | M | Registrar diagnóstico y solución propuesta | Texto guardado y visible en el detalle |
| RF-12 | M | Generar mensajes con plantilla o GPT supervisado | El mensaje pasa la validación antes de enviarse |
| RF-13 | M | Registrar intentos de notificación y su estado | Fila en `notifications` con estado y error si lo hubo |
| RF-14 | M | Simular envío y recepción sin API externa | Flujo completo demostrable solo con el simulador |
| RF-15 | M | Procesar "Sí, se solucionó" y cerrar | Una sola transición a `CERRADO` |
| RF-16 | M | Procesar "No, continúa" y reabrir | Una sola transición a `REABIERTO` y aviso al técnico |
| RF-17 | M | Consultar la auditoría de cada ticket | Eventos en orden cronológico, filtrables por tipo |
| RF-18 | M | Mostrar indicadores mínimos | Cifras iguales a una consulta directa a la base |
| RF-19 | D | Notificación real por WhatsApp Cloud API | Envío y recepción en entorno de prueba de Meta |
| RF-20 | D | Escalar el incumplimiento de plazo | Evento `SLA_BREACHED` y alerta al administrador |
| RF-21 | D | Clasificar con la API real de GPT (salida estructurada) | Respuesta validada contra el esquema 13.1 |
| RF-22 | D | Exportar reportes en CSV | Archivo descargable con los tickets filtrados |
| RF-23 | F | Registrar tickets desde WhatsApp | — |
| RF-24 | F | Analizar fotos y adjuntos | — |

## 5. Requisitos no funcionales

| ID | Categoría | Requisito | Cómo se comprueba |
|---|---|---|---|
| RNF-01 | Seguridad | Contraseñas con argon2id; permisos por rol y por objeto | Pruebas de login y de acceso indebido |
| RNF-02 | Privacidad | Logs sin claves, tokens, contraseñas, mensajes completos ni teléfonos sin enmascarar | Revisión de logs en pruebas |
| RNF-03 | Disponibilidad | La gestión de tickets no depende de GPT ni de WhatsApp | Pruebas con proveedores caídos |
| RNF-04 | Integridad | Ticket + evento inicial + trabajo de outbox en una transacción | Prueba de rollback |
| RNF-05 | Trazabilidad | Cada evento guarda actor, acción, estados, fecha y `correlation_id` | Revisión de eventos por ticket |
| RNF-06 | Rendimiento | El alta responde sin esperar a servicios externos | El alta no llama a adaptadores externos |
| RNF-07 | Usabilidad | Mensajes de error legibles y estados con etiqueta en español | Revisión de pantallas |
| RNF-08 | Mantenibilidad | Capas separadas y pruebas automatizadas | Estructura del repositorio y `pytest` |
| RNF-09 | Portabilidad | Se levanta en local siguiendo el README | Otro integrante lo instala desde cero |
| RNF-10 | Resiliencia | Reintentos limitados y registrados | Simular 429, 500 y timeout |
| RNF-11 | Control | Operaciones sensibles con autorización y evento | Casos negativos de la API |
| RNF-12 | Consistencia | Webhooks y respuestas repetidas no duplican efectos | Prueba de idempotencia |

---

## 6. Reglas de negocio

| ID | Regla | Comportamiento |
|---|---|---|
| RN-01 | Validación | No se guardan tickets incompletos; error legible y sin registro parcial |
| RN-02 | Código único | Secuencia de PostgreSQL `ticket_code_seq`; formato `TRZ-` + número con 4 dígitos mínimo |
| RN-03 | Priorización | La prioridad final sale siempre de la matriz 7.1 |
| RN-04 | Revisión crítica | Categoría `SEGURIDAD` o confianza menor a 0,6 → `review_required = true`; no hay asignación automática hasta que el administrador valide |
| RN-05 | Fallback IA | GPT caído, lento (timeout) o con salida inválida → `rule_provider` y evento `CLASSIFICATION_FALLBACK` |
| RN-06 | Control de estados | Solo transiciones de la tabla 8.2; las demás lanzan `InvalidTransition` |
| RN-07 | Asignación | Solo técnicos activos; automática al de menor carga abierta (empate: menor `id`) |
| RN-08 | Auditoría | Toda acción relevante crea un evento; los eventos no se editan ni se borran |
| RN-09 | Notificaciones | Cada envío tiene `idempotency_key` y estado propio |
| RN-10 | Confirmación | El técnico no puede cerrar; solo propone la solución |
| RN-11 | Reapertura | Un "No" válido reabre exactamente una vez y avisa al técnico |
| RN-12 | Sin respuesta | El silencio no cierra; recordatorio y alerta al administrador |
| RN-13 | Escalamiento | Plazo vencido → `SLA_BREACHED` (una vez por ticket y prioridad) |
| RN-14 | Protección de datos | Solo se usa el teléfono de usuarios con `whatsapp_opt_in = true`; a GPT no se envían nombres, teléfonos ni correos |
| RN-15 | Webhook idempotente | Un mismo evento del proveedor procesado dos veces produce un solo cambio |

---

## 7. Prioridad y plazos

### 7.1 Matriz de prioridad (`services/priority_rules.py`)

| Impacto \ Urgencia | `BAJA` | `MEDIA` | `ALTA` |
|---|---|---|---|
| `INDIVIDUAL` (una persona) | `BAJA` | `MEDIA` | `ALTA` |
| `EQUIPO` (equipo pequeño) | `MEDIA` | `ALTA` | `ALTA` |
| `AREA` (área completa) | `ALTA` | `ALTA` | `CRITICA` |

La matriz es una función pura `compute_priority(impact, urgency) -> Priority`, sin acceso a base de datos, con versión `rules_version = "v1"` guardada en cada clasificación.

### 7.2 Plazos de demostración (configurables por variables de entorno)

| Prioridad | Plazo de primera atención | Al vencer |
|---|---|---|
| `CRITICA` | 15 min | `SLA_BREACHED` + alerta al administrador |
| `ALTA` | 30 min | `SLA_BREACHED` + alerta al administrador |
| `MEDIA` | 2 h | `SLA_BREACHED` + recordatorio al técnico |
| `BAJA` | 24 h | `SLA_BREACHED` + recordatorio al técnico |

"Primera atención" = paso a `EN_PROCESO` (`tickets.first_response_at`). El worker revisa plazos en cada ciclo.

---

## 8. Estados del ticket

### 8.1 Estados (`TicketStatus`)

| Estado | Significado |
|---|---|
| `PENDIENTE` | Registrado, sin técnico |
| `ASIGNADO` | Técnico responsable definido |
| `EN_PROCESO` | El técnico está trabajando |
| `PENDIENTE_CONFIRMACION` | El técnico propuso una solución; falta la respuesta del solicitante |
| `CERRADO` | El solicitante confirmó (o cierre excepcional del administrador) |
| `REABIERTO` | El solicitante indicó que el problema continúa |

### 8.2 Transiciones válidas

Toda transición pasa por `ticket_service.transition(ticket, to_status, actor, reason=None)`, que valida la tabla, el rol, la versión del ticket y escribe los eventos.

| Desde | Hacia | Quién | Condición | Eventos |
|---|---|---|---|---|
| (nuevo) | `PENDIENTE` | Solicitante | Datos válidos | `TICKET_CREATED` |
| `PENDIENTE` | `ASIGNADO` | Admin o sistema | Técnico activo; sin revisión pendiente si es automática | `TICKET_ASSIGNED`, `TICKET_STATUS_CHANGED` |
| `ASIGNADO`, `EN_PROCESO` | `ASIGNADO` | Admin | Reasignación con motivo | `TICKET_ASSIGNED` |
| `ASIGNADO` | `EN_PROCESO` | Técnico asignado | — | `TICKET_STATUS_CHANGED` |
| `EN_PROCESO` | `PENDIENTE_CONFIRMACION` | Técnico asignado | Texto de solución obligatorio | `RESOLUTION_PROPOSED`, `TICKET_STATUS_CHANGED`, `CONFIRMATION_REQUESTED` |
| `PENDIENTE_CONFIRMACION` | `CERRADO` | Solicitante del ticket | Respuesta Sí válida | `CONFIRMATION_ACCEPTED`, `TICKET_STATUS_CHANGED` |
| `PENDIENTE_CONFIRMACION` | `REABIERTO` | Solicitante del ticket | Respuesta No válida | `CONFIRMATION_REJECTED`, `TICKET_REOPENED` |
| `PENDIENTE_CONFIRMACION` | (sin cambio) | Sistema | Sin respuesta tras `REMINDER_AFTER_MINUTES` | `CONFIRMATION_REMINDER`, `ADMIN_ALERT` |
| `REABIERTO` | `EN_PROCESO` | Técnico asignado | Retoma el caso | `TICKET_STATUS_CHANGED` |
| `REABIERTO` | `ASIGNADO` | Admin | Reasignación con motivo | `TICKET_ASSIGNED`, `TICKET_STATUS_CHANGED` |
| `PENDIENTE_CONFIRMACION` | `CERRADO` | Admin (D) | Cierre excepcional con motivo obligatorio | `TICKET_CLOSED_BY_ADMIN` (nunca `CONFIRMATION_ACCEPTED`) |

Cualquier otra combinación (por ejemplo `PENDIENTE` → `CERRADO`) lanza `InvalidTransition` → HTTP 409. Concurrencia: `tickets.version` con bloqueo optimista; si la versión no coincide → HTTP 409.

El recordatorio se envía una sola vez por ciclo de confirmación. Si el ticket se reabre y vuelve a `PENDIENTE_CONFIRMACION`, empieza un ciclo nuevo.

---

## 9. Flujos clave

### 9.1 Registrar solicitud (CU-02)

1. El solicitante envía título (5–120 caracteres), descripción (10–2000), ubicación opcional (hasta 120).
2. Se valida con Pydantic; si falla, se muestra el error junto al campo.
3. En **una transacción**: se crea el ticket en `PENDIENTE` con su código, el evento `TICKET_CREATED` y el trabajo `CLASSIFY_TICKET` en `outbox_jobs`. Si el solicitante aceptó WhatsApp, también el trabajo `SEND_NOTIFICATION` (mensaje A1).
4. Se responde y se redirige al detalle del ticket con su código.
5. Después, el worker clasifica, calcula la prioridad y, si no hace falta revisión, asigna automáticamente.

Postcondición: el ticket existe aunque GPT y WhatsApp fallen después.

### 9.2 Confirmar o rechazar (CU-09 y CU-10)

Entradas posibles: botón del simulador (`source = SIMULATOR`), formulario web del solicitante (`WEB`) o webhook de WhatsApp (`WHATSAPP`). Las tres llaman a `confirmation_service.register_answer(...)`, que:

1. Comprueba que el ticket exista y esté en `PENDIENTE_CONFIRMACION`.
2. Comprueba que quien responde sea el solicitante del ticket.
3. Comprueba la idempotencia: si `provider_event_id` (o la clave de la respuesta web) ya existe, no hace nada y lo registra como duplicado.
4. Guarda la fila en `confirmations` y aplica la transición correspondiente en la misma transacción.
5. Programa el mensaje de resultado (A4 o A5) y, si fue No, el aviso al técnico.

Respuesta tardía (ticket ya cerrado o reabierto): no cambia nada y se registra el intento.

---

## 10. Eventos de dominio (`EventType`)

| Evento | Emisor | Detalle mínimo en `safe_details_json` |
|---|---|---|
| `TICKET_CREATED` | Solicitante | — |
| `TICKET_CLASSIFIED` | Sistema | proveedor, categoría, impacto, urgencia, prioridad |
| `CLASSIFICATION_FALLBACK` | Sistema | motivo (`timeout`, `invalid_output`, `provider_error`) |
| `CLASSIFICATION_VALIDATED` | Admin | valores anteriores y nuevos |
| `TICKET_ASSIGNED` | Admin o sistema | técnico, motivo |
| `TICKET_STATUS_CHANGED` | Varios | `old_state`, `new_state` en sus columnas |
| `RESOLUTION_PROPOSED` | Técnico | resumen corto de la solución |
| `CONFIRMATION_REQUESTED` | Sistema | id de la notificación |
| `CONFIRMATION_ACCEPTED` | Solicitante | fuente |
| `CONFIRMATION_REJECTED` | Solicitante | fuente |
| `TICKET_REOPENED` | Sistema | número de reapertura |
| `CONFIRMATION_REMINDER` | Sistema | — |
| `ADMIN_ALERT` | Sistema | motivo |
| `NOTIFICATION_SENT` | Sistema | tipo de mensaje, canal |
| `NOTIFICATION_FAILED` | Sistema | código de error, intento |
| `SLA_BREACHED` | Sistema | prioridad, plazo |
| `DUPLICATE_ANSWER_IGNORED` | Sistema | fuente, id del evento externo |
| `TICKET_CLOSED_BY_ADMIN` | Admin (D) | motivo |

## 11. Errores previstos

| Situación | Nunca debe pasar | Manejo |
|---|---|---|
| GPT no responde (clasificación) | Perder el ticket | Reglas locales + `CLASSIFICATION_FALLBACK` |
| GPT no responde (redacción) | Bloquear el flujo | Plantilla fija |
| WhatsApp rechaza el envío | Marcarlo como entregado | `FAILED`, código de error y reintento |
| Webhook o respuesta duplicada | Cerrar o reabrir dos veces | Clave única + `DUPLICATE_ANSWER_IGNORED` |
| Acceso a ticket ajeno | Mostrar datos | 403 |
| Dos cambios simultáneos | Sobrescribir el estado | Versión optimista → 409 |
| Datos incompletos | Guardar inconsistencias | 422 con detalle por campo |
| Falta de confirmación | Presumir satisfacción | Sigue pendiente + recordatorio |
| Falla de base de datos | Enviar un mensaje sin ticket | Nada sale hasta confirmar la transacción (outbox) |

---

## 12. Modelo de datos

Todas las tablas con `id` entero autoincremental, `created_at timestamptz default now()`. Enums guardados como texto con `CHECK` (más simple de migrar que los enums nativos).

**`users`**: `id`, `full_name`, `email` (único), `password_hash`, `phone_e164` (nulo), `role` (`REQUESTER` | `TECHNICIAN` | `ADMIN`), `whatsapp_opt_in` (bool, default false), `is_active` (bool), `created_at`.

**`tickets`**: `id`, `public_code` (único), `requester_id` → users, `title`, `description`, `location` (nulo), `category` (nulo hasta clasificar), `impact`, `urgency`, `priority` (nulos hasta clasificar), `review_required` (bool), `status`, `assigned_technician_id` → users (nulo), `resolution_text` (nulo), `reopen_count` (int, default 0), `version` (int), `created_at`, `updated_at`, `first_response_at`, `closed_at`, `sla_breached_at`. Índices: `public_code`, `status`, `assigned_technician_id`, `requester_id`, `created_at`.

**`classifications`**: `id`, `ticket_id`, `provider` (`openai` | `rules` | `mock` | `manual`), `category_suggested`, `impact_suggested`, `urgency_suggested`, `priority_computed`, `confidence` (nulo), `review_required`, `rationale` (nulo, ≤ 200), `rules_version`, `model_version` (nulo), `validated_by` → users (nulo), `created_at`.

**`assignments`**: `id`, `ticket_id`, `technician_id`, `assigned_by` (nulo si fue el sistema), `reason`, `assigned_at`, `released_at` (nulo).

**`ticket_events`** (solo inserción): `id`, `ticket_id`, `event_type`, `actor_type` (`USER` | `SYSTEM` | `INTEGRATION`), `actor_id` (nulo), `old_state`, `new_state` (nulos), `safe_details_json` (jsonb), `correlation_id` (uuid), `created_at`. Índice `(ticket_id, created_at)`.

**`notifications`**: `id`, `ticket_id`, `channel` (`WHATSAPP` | `SIMULATED`), `recipient_user_id`, `message_type` (A1–A6), `body`, `provider_message_id` (nulo), `status` (`PENDING` | `SENT` | `DELIVERED` | `READ` | `FAILED` | `RETRYING` | `SIMULATED`), `attempt_count`, `last_error_code` (nulo), `idempotency_key` (único), `created_at`, `sent_at`, `delivered_at`.

**`confirmations`**: `id`, `ticket_id`, `requester_id`, `notification_id` (nulo), `answer` (`YES` | `NO`), `source` (`WHATSAPP` | `WEB` | `SIMULATOR`), `provider_event_id` (único, nulo para web), `confirmation_round` (int: 1 en el primer ciclo, 2 tras una reapertura…), `responded_at`. Restricción única `(ticket_id, confirmation_round)`: una sola respuesta válida por ciclo.

**`outbox_jobs`**: `id`, `ticket_id` (nulo), `job_type` (`CLASSIFY_TICKET` | `AUTO_ASSIGN` | `SEND_NOTIFICATION`), `payload_safe_json` (jsonb), `status` (`PENDING` | `RUNNING` | `DONE` | `FAILED`), `attempts`, `next_run_at`, `last_error` (nulo), `created_at`, `completed_at`.

---

## 13. Integraciones

Todas detrás de interfaces (`typing.Protocol`) en `integrations/`, elegidas por variable de entorno. Las pruebas usan siempre los simuladores.

### 13.1 Clasificación (`ClassificationProvider`)

`classify(text: TicketText) -> ClassificationResult`. Implementaciones: `MockProvider` (respuestas fijas por palabra clave, para demo y pruebas), `RuleProvider` (palabras clave) y `OpenAIProvider`.

Esquema de salida (el mismo para todas):

```json
{
  "category": "REDES | HARDWARE | SOFTWARE | ACCESOS | SEGURIDAD | OTROS",
  "impact": "INDIVIDUAL | EQUIPO | AREA",
  "urgency": "BAJA | MEDIA | ALTA",
  "human_review_required": false,
  "confidence": 0.91,
  "rationale": "Laboratorio completo sin conexión y con clase próxima."
}
```

- `OpenAIProvider` usa salida estructurada (JSON Schema estricto), timeout de `OPENAI_TIMEOUT_SECONDS` y solo envía título, descripción y ubicación, nunca datos personales. Cualquier excepción, timeout o salida que no valide con Pydantic → fallback a `RuleProvider`.
- `RuleProvider`: urgencia `ALTA` si aparecen palabras como "urgente", "clase", "examen", "no funciona nada"; impacto `AREA` con "laboratorio", "todo", "toda el área", "oficina"; `EQUIPO` con "varios", "equipo", números de personas mayores a 1; categoría por listas de palabras (red/internet/wifi → `REDES`, impresora/monitor → `HARDWARE`, contraseña/acceso/cuenta → `ACCESOS`, phishing/credenciales/virus → `SEGURIDAD`). Valores por defecto: `OTROS`, `INDIVIDUAL`, `MEDIA`.
- Después de clasificar, el servicio aplica RN-04 (seguridad o confianza baja → revisión) y la matriz 7.1. La IA nunca escribe la prioridad.

### 13.2 Redacción de mensajes (`MessageComposer`)

`compose(message_type, context) -> str`. Implementaciones: `TemplateComposer` (plantillas del anexo A, por defecto) y `OpenAIComposer`. El contexto solo lleva datos verificados: tipo de evento, código, estado, siguiente paso y nombre de pila si está autorizado.

Validación antes de enviar (si falla, se usa la plantilla): máximo 500 caracteres; contiene el código del ticket; no dice "cerrado" o "resuelto" si el estado no lo es; sin URLs; sin teléfonos ni correos.

### 13.3 Notificaciones (`NotificationProvider`)

`send(notification) -> SendResult`. Implementaciones: `SimulatedWhatsApp` (por defecto: guarda el mensaje como `SIMULATED` y lo muestra en la página `/simulador`) y `WhatsAppCloudProvider` (D).

Webhook real (`/webhooks/whatsapp`), en este orden:
1. `GET` de verificación: responde `hub.challenge` si `hub.verify_token` coincide con `WHATSAPP_VERIFY_TOKEN`.
2. `POST`: valida la firma `X-Hub-Signature-256` (HMAC-SHA256 del cuerpo con `WHATSAPP_APP_SECRET`); firma inválida → 401 sin cambios.
3. Extrae el id externo del mensaje; si ya se procesó → 200 sin efectos.
4. Identifica el ticket y el destinatario a partir del mensaje original (`provider_message_id`) y llama a `confirmation_service`.
5. Los avisos de estado de entrega (`sent`, `delivered`, `read`, `failed`) solo actualizan `notifications`.

### 13.4 Simulador (obligatorio)

Página `/simulador` (solo en entorno de desarrollo o para el administrador) que muestra, por solicitante, los mensajes "enviados" como un chat, con los botones "Sí, se solucionó" y "No, continúa" bajo la pregunta de confirmación. Al pulsar, llama al mismo `confirmation_service` con `source = SIMULATOR` y un `provider_event_id` generado. Sirve para la demo y para las pruebas de aceptación.

### 13.5 Worker y outbox (`workers/process_outbox.py`)

- Bucle cada `OUTBOX_POLL_SECONDS`: toma trabajos `PENDING` con `next_run_at <= now()` usando `SELECT … FOR UPDATE SKIP LOCKED`, los marca `RUNNING` y los ejecuta.
- Éxito → `DONE`. Error → `attempts + 1`, `next_run_at` con espera exponencial (1, 2, 4, 8, 16 min) y `last_error`. Al llegar a `OUTBOX_MAX_ATTEMPTS` → `FAILED`, evento y `ADMIN_ALERT`.
- En cada ciclo también revisa plazos (7.2) y recordatorios de confirmación.
- Un trabajo `RUNNING` con más de 10 minutos se considera abandonado y vuelve a `PENDING` (recuperación tras reinicio, CP-18).

---

## 14. API y páginas

Rutas JSON bajo `/api`. Todas exigen sesión salvo login, health y webhook.

| Método | Ruta | Rol | Propósito |
|---|---|---|---|
| `POST` | `/api/auth/login` | Público | Iniciar sesión |
| `POST` | `/api/auth/logout` | Cualquiera | Cerrar sesión |
| `GET` | `/api/me` | Cualquiera | Datos y rol propios |
| `POST` | `/api/tickets` | Solicitante | Registrar ticket |
| `GET` | `/api/tickets` | Según rol | Listar (filtros: estado, prioridad) |
| `GET` | `/api/tickets/{code}` | Según rol | Detalle |
| `GET` | `/api/tickets/{code}/events` | Según rol | Bitácora |
| `POST` | `/api/tickets/{code}/classification` | Admin | Validar o corregir la clasificación |
| `POST` | `/api/tickets/{code}/assign` | Admin | Asignar o reasignar (con motivo) |
| `POST` | `/api/tickets/{code}/start` | Técnico asignado | Iniciar o retomar atención |
| `POST` | `/api/tickets/{code}/resolve` | Técnico asignado | Proponer solución |
| `POST` | `/api/tickets/{code}/confirm` | Solicitante | Responder Sí o No (web) |
| `GET` | `/api/dashboard/metrics` | Admin | Indicadores |
| `GET/POST` | `/webhooks/whatsapp` | Proveedor | Verificación y eventos |
| `GET` | `/health` | Público | Estado del servicio y de la base |

Páginas (Jinja2): `/login`, `/tickets` (lista según rol), `/tickets/nuevo`, `/tickets/{code}` (detalle, línea de tiempo y acciones según rol y estado), `/admin` (bandeja con filtros y reasignación), `/monitoreo` (indicadores y alertas), `/simulador`.

## 15. Indicadores (`/api/dashboard/metrics`)

Tickets por estado y por prioridad; tickets pendientes de confirmación; tasa de reapertura (tickets con `reopen_count > 0` / tickets que pasaron por confirmación); notificaciones `FAILED`; plazos vencidos; tiempo medio hasta la primera atención; tiempo medio hasta el cierre confirmado; clasificaciones por proveedor (cuántas por GPT, reglas o manual). Todo calculado con consultas a la base, sin valores fijos.

---

## 16. Mensajes (plantillas por defecto)

| Tipo | Texto |
|---|---|
| A1 Ticket recibido | Hola, {nombre}. TRAZA registró tu solicitud {codigo}. Estado: Pendiente. Te avisaremos cuando sea asignada a un técnico. |
| A2 Técnico asignado | Tu solicitud {codigo} fue asignada al equipo de soporte. Estado: En atención. |
| A3 Pedido de confirmación | El equipo técnico registró una solución para {codigo}. ¿El problema quedó solucionado? |
| A4 Cierre confirmado | Gracias por confirmar. Tu solicitud {codigo} quedó cerrada. TRAZA conserva el historial de la atención. |
| A5 Reapertura | Recibimos tu respuesta. La solicitud {codigo} fue reabierta porque el problema continúa. Avisamos al técnico responsable. |
| A6 Falla de envío (solo admin) | No se pudo enviar el mensaje del ticket {codigo}. Intento {n}. Se programó un nuevo intento o requiere revisión. |
| A7 Recordatorio | Recordatorio: aún no nos confirmas si se resolvió {codigo}. |
| A8 Aviso al técnico | El solicitante indicó que el problema de {codigo} continúa. El ticket volvió a tu bandeja. |

---

## 17. Casos de prueba

| ID | Caso | Condición | Resultado esperado |
|---|---|---|---|
| CP-01 | Alta correcta | Campos válidos | Ticket, evento `TICKET_CREATED` y trabajo de outbox |
| CP-02 | Formulario inválido | Descripción vacía | 422; no se guarda nada |
| CP-03 | Permisos | Solicitante pide ticket ajeno | 403 |
| CP-04 | Código único | Altas concurrentes | Sin códigos duplicados |
| CP-05 | Prioridad | Impacto `AREA` + urgencia `ALTA` | `CRITICA` |
| CP-06 | Caída de IA | Timeout del proveedor | Clasificado por reglas + `CLASSIFICATION_FALLBACK` |
| CP-07 | Asignación | Técnico inactivo | No se le asigna |
| CP-08 | Estado inválido | `PENDIENTE` → `CERRADO` | 409; estado intacto |
| CP-09 | Auditoría | Cambio de estado válido | Evento con actor y hora |
| CP-10 | Falla de WhatsApp | Error del proveedor | Ticket intacto; notificación `FAILED` |
| CP-11 | Reintento | Falla temporal | Reintentos limitados y registrados |
| CP-12 | Confirmación Sí | Ticket pendiente, usuario correcto | `CERRADO` una vez |
| CP-13 | Confirmación No | Ticket pendiente, usuario correcto | `REABIERTO` y aviso al técnico |
| CP-14 | Confirmación duplicada | Misma respuesta dos veces | Un solo cambio + `DUPLICATE_ANSWER_IGNORED` |
| CP-15 | Sin respuesta | Vence el plazo de recordatorio | Sigue pendiente; recordatorio y alerta |
| CP-16 | Webhook inválido | Firma incorrecta | 401 sin cambios |
| CP-17 | Métricas | Dataset conocido | Cifras iguales a la consulta directa |
| CP-18 | Recuperación | Trabajo `RUNNING` abandonado | Se retoma sin perder el ticket |

Además: una prueba por cada fila de la matriz 7.1, una por cada transición válida y varias inválidas, y una prueba de aceptación del ciclo completo (alta → clasificación → asignación → atención → solución → No → retoma → solución → Sí → cerrado) con el simulador.

---

## 18. Plan de implementación

| Fase | Semanas | Qué se construye | Listo cuando |
|---|---|---|---|
| 1. Núcleo | 9–10 | Estructura del repo, configuración, Docker con PostgreSQL, modelos y migraciones, seed, login con roles, alta y listado de tickets con código único, evento `TICKET_CREATED`, páginas login / lista / nuevo / detalle básico | Pasan CP-01 a CP-04 |
| 2. Control | 11 | Máquina de estados, asignación manual y automática, bitácora en el detalle, matriz de prioridad, `RuleProvider` + `MockProvider`, outbox y worker, notificaciones simuladas, confirmación por web y simulador | Pasan CP-05, 07, 08, 09, 12, 13, 14, 18 y el ciclo completo con simulador |
| 3. IA y mensajes | 12–13 | `OpenAIProvider` con salida estructurada y fallback, validación de clasificación por el admin, `MessageComposer` con validación | Pasa CP-06; demo con GPT real o con reglas |
| 4. Confirmación | 14 | Recordatorios, plazos, webhook con firma e idempotencia; WhatsApp real si hay credenciales | Pasan CP-10, 11, 15, 16 |
| 5. Pruebas y entrega | 15–16 | Panel de monitoreo, métricas, pruebas de aceptación, evidencias, README final | Pasa CP-17; todos los M verificados |

## 19. Datos de prueba (seed)

Usuarios (contraseña común de desarrollo definida en `.env`): 1 administrador, 2 técnicos activos y 1 inactivo, 3 solicitantes (uno sin aceptar WhatsApp). Todos con nombres y correos ficticios (`@traza.test`).

| Ticket | Descripción | Categoría | Impacto | Urgencia | Prioridad esperada |
|---|---|---|---|---|---|
| TRZ-0001 | Laboratorio de cómputo 3 sin internet, tengo clase en una hora | REDES | AREA | ALTA | CRITICA |
| TRZ-0002 | Impresora personal sin tinta | HARDWARE | INDIVIDUAL | BAJA | BAJA |
| TRZ-0003 | No puedo entrar a la plataforma interna | ACCESOS | INDIVIDUAL | MEDIA | MEDIA |
| TRZ-0004 | Tres compañeros sin acceso al sistema de trámites | SOFTWARE | EQUIPO | ALTA | ALTA |
| TRZ-0005 | Posible exposición de credenciales por un correo sospechoso | SEGURIDAD | (por evaluar) | ALTA | Revisión humana |

## 20. Variables de entorno (`.env.example`)

```dotenv
APP_ENV=development
SECRET_KEY=
DATABASE_URL=postgresql+psycopg://traza:traza@localhost:5432/traza
TEST_DATABASE_URL=postgresql+psycopg://traza:traza@localhost:5432/traza_test
TIMEZONE=America/Lima
SEED_PASSWORD=

CLASSIFIER_PROVIDER=mock            # mock | rules | openai
MESSAGE_COMPOSER=templates          # templates | openai
NOTIFICATION_PROVIDER=simulated     # simulated | whatsapp

OPENAI_API_KEY=
OPENAI_MODEL=
OPENAI_TIMEOUT_SECONDS=10

WHATSAPP_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_APP_SECRET=
WHATSAPP_VERIFY_TOKEN=

OUTBOX_POLL_SECONDS=5
OUTBOX_MAX_ATTEMPTS=5
REMINDER_AFTER_MINUTES=120
SLA_CRITICA_MINUTES=15
SLA_ALTA_MINUTES=30
SLA_MEDIA_MINUTES=120
SLA_BAJA_MINUTES=1440
```

## 21. Decisiones pendientes

- Modelo de OpenAI y límite de gasto (queda configurable en `OPENAI_MODEL`).
- WhatsApp real o solo simulador en la semana 16.
- Cierre excepcional del administrador (marcado como D en 8.2).
- Asignación por especialidad del técnico (hoy solo por carga).
- Nombre oficial de la unidad de TI de la FISI para la interfaz.
