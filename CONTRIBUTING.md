# Guía de contribución

- **Ramas:** `main` (estable, desplegada), `develop` (integración), `feature/<tema>` y `fix/<tema>`. Se integra por pull request.
- **Commits:** prefijos `feat`, `fix`, `test`, `docs`, `infra`, `chore`; mensaje en imperativo y en español, una idea por commit.
- **Antes de abrir un PR:** `python -m tests.run_all` debe terminar sin fallos y no deben subirse secretos (`.env`, `demo_keys.json`).
- **Revisión:** el PR usa la plantilla de `.github/pull_request_template.md`; se revisa seguridad (validación, roles), pruebas y documentación.
