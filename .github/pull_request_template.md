## Qué cambia

<!-- Una o dos frases. ¿Qué problema resuelve o qué agrega? -->

## Alcance

- Fase del plan (sección 18): <!-- 1, 2, 3, 4 o 5 -->
- Requisitos y casos que cubre: <!-- p. ej. RF-21, RN-05, CP-06 -->
- Reglas de `CLAUDE.md` que toca: <!-- p. ej. regla 4 (la IA sugiere, las reglas deciden), o "ninguna" -->

## Cómo probarlo

<!-- Pasos para que quien revisa lo vea funcionar: usuario del seed, página, comando del worker, etc. -->

1.
2.

## Revisión antes de pedir aprobación

- [ ] `pytest` pasa en mi máquina (resultado real: `__ passed`)
- [ ] `ruff check .` y `ruff format --check .` sin errores
- [ ] Cada regla o requisito nuevo tiene al menos una prueba, nombrada con su caso (`test_cp06_...`)
- [ ] Las pruebas no llaman a OpenAI ni a WhatsApp reales
- [ ] Sin claves, tokens, `.env` ni datos personales reales en el código o en los commits
- [ ] Si agregué una migración: partí de `main` actualizado y `alembic heads` muestra una sola cabeza
- [ ] Si tomé una decisión fuera de la especificación, la anoté en `docs/decisiones.md`
- [ ] Si cambiaron comandos o variables de entorno, actualicé `README.md`, `CLAUDE.md` o `.env.example`

## Capturas (si cambia la interfaz)

<!-- Opcional. Arrastra aquí las imágenes. -->
