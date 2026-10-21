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
