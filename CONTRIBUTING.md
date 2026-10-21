# Cómo contribuir a TRAZA

Guía de trabajo del grupo G3. Las reglas técnicas del proyecto están en [`CLAUDE.md`](CLAUDE.md) y la especificación en [`docs/especificacion.md`](docs/especificacion.md); esta guía explica cómo integramos el trabajo de varias personas sin pisarnos.

## 1. Antes del primer commit

1. Clona el repositorio e instala el proyecto siguiendo el [README](README.md).
2. Crea tu `.env` a partir de `.env.example`, con tu propia `SECRET_KEY` y `SEED_PASSWORD`. **El `.env` nunca se sube.**
3. Configura tu identidad de git con el correo que tienes registrado en GitHub; si no, tus commits no aparecerán asociados a tu cuenta:

   ```bash
   git config --global user.name "Nombre Apellido"
   git config --global user.email "tu-correo@ejemplo.com"
   ```

4. Comprueba que todo funciona: `pytest` debe pasar completo.

## 2. Ramas

- `main` está protegida: nadie sube directo; todo entra por pull request con una aprobación y las pruebas en verde.
- Cada tarea va en su propia rama, creada desde `main` actualizado:

  ```bash
  git switch main
  git pull
  git switch -c feature/nombre-del-modulo
  ```

- Prefijos de rama:

  | Prefijo | Para qué | Ejemplo |
  |---|---|---|
  | `feature/` | Funcionalidad nueva | `feature/ia`, `feature/monitoreo` |
  | `fix/` | Corrección de un error | `fix/version-en-asignacion` |
  | `chore/` | Configuración, CI, dependencias | `chore/colaboracion` |
  | `docs/` | Solo documentación | `docs/informe-pruebas` |

- Una rama por módulo o tarea, no por persona. Si dos personas necesitan tocar los mismos archivos, conversen antes (ver sección 6).

## 3. Commits

- En español y en imperativo: "Agrega webhook de WhatsApp", "Corrige el cálculo de la versión".
- Pequeños y enfocados: un commit por unidad lógica (un servicio, una prueba, una plantilla). Que cada commit se entienda solo.
- Nunca incluyas claves, tokens, el `.env`, teléfonos o correos reales. Los datos de prueba son sintéticos y usan el dominio `@traza.test`.
- Antes de cada commit:

  ```bash
  ruff check .
  ruff format .
  pytest
  ```

## 4. Pull requests

1. Sube tu rama y abre un pull request hacia `main`:

   ```bash
   git push -u origin feature/nombre-del-modulo
   ```

2. Completa la plantilla: qué cambia, qué requisitos y casos cubre (RF, RN, CP), cómo probarlo y la lista de revisión.
3. GitHub Actions corre automáticamente `ruff`, la verificación de migraciones y `pytest` contra un PostgreSQL de prueba. Si algo falla, corrígelo en la misma rama: el PR se actualiza solo.
4. Otra persona del grupo revisa. Quien revisa comprueba al menos:
   - que se respeten las 9 "reglas que no se rompen" de `CLAUDE.md`;
   - que cada regla o requisito nuevo tenga su prueba;
   - que el flujo de dependencias siga siendo `api → services → repositories → models`;
   - que las decisiones fuera de la especificación estén en `docs/decisiones.md`.
5. Si `main` avanzó y hay conflictos, quien abrió el PR los resuelve en su rama:

   ```bash
   git switch feature/nombre-del-modulo
   git pull origin main
   # resolver conflictos, volver a correr pytest
   git push
   ```

6. Con la aprobación y las pruebas en verde, se integra con **"Create a merge commit"** (conserva los commits por unidad lógica) y se borra la rama.

## 5. Migraciones de Alembic

Dos ramas que crean migraciones a la vez generan dos "cabezas" y rompen `alembic upgrade head`. Para evitarlo:

1. Antes de crear una migración, actualiza tu rama con `main` (`git pull origin main`).
2. Avisa al grupo que estás creando una migración y con qué número (`0003_...`, `0004_...`).
3. Escríbela a mano y revísala: los enums van como texto con `CHECK`, las fechas en `timestamptz`.
4. Comprueba que hay una sola cabeza y que la migración sube y baja:

   ```bash
   alembic heads
   alembic downgrade -1
   alembic upgrade head
   ```

5. Si al integrar aparecen dos cabezas (el CI lo detecta), quien integra **segundo** cambia el `down_revision` de su migración para que apunte a la del otro, la renumera y vuelve a probar.

## 6. Repartir el trabajo

Lo que más conflictos produce es que dos personas editen los mismos archivos. Repartimos por módulo y avisamos en el grupo qué archivos vamos a tocar. Archivos compartidos que conviene coordinar:

- `backend/services/ticket_service.py` (máquina de estados) y `backend/services/notification_service.py`;
- `backend/workers/process_outbox.py`;
- `backend/models/enums.py` y las migraciones;
- `backend/templates/base.html` y `backend/core/templating.py`.

## 7. Pruebas

- Cada requisito imprescindible (RF-01 a RF-18) y cada regla de `CLAUDE.md` tiene al menos una prueba.
- Nombra las pruebas con el caso que cubren: `test_cp08_pendiente_a_cerrado_rechazado`.
- Las pruebas nunca llaman a OpenAI ni a WhatsApp reales: usan `mock_provider`, `rule_provider`, `simulated_whatsapp` o proveedores falsos (`tests/helpers.py`).
- Cada prueba corre en una transacción que se revierte; usa los fixtures de `tests/conftest.py` (`db`, `actors`, `login`, `make_user`).
- No inventes resultados: el informe final usa solo resultados reales de `pytest` y del CI.

## 8. Si usas Claude Code

`CLAUDE.md` se carga solo y aplica las mismas reglas: trabajar por fases, proponer un plan antes de cambios grandes, commits en español, ramas por módulo y nunca hacer push ni merge a `main` sin pedirlo. Revisa siempre lo que genere antes de abrir el PR: la responsabilidad del código es de quien lo sube.

## 9. Configuración del repositorio (solo para quien lo administra)

En GitHub, **Settings → Branches → Add branch protection rule** para `main`:

- **Require a pull request before merging**, con 1 aprobación.
- **Require status checks to pass before merging**, eligiendo el check **pytest y ruff**. Aparece en la lista después de la primera corrida del workflow.
- **Require branches to be up to date before merging**.

En **Settings → General → Pull Requests**, deja activa solo **Allow merge commits** y marca **Automatically delete head branches**.
