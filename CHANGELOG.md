# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] — 2026-04-23

### Added
- Initial plugin skeleton with QGIS 3.22+ LTR support
- Settings dialog with encrypted API key storage (`QgsAuthManager`) and
  plain `QSettings` fallback when no master password is set
- `PudumapsClient` HTTP wrapper (CRUD for projects and layers) with
  automatic retry on 429 respecting `X-RateLimit-Reset`
- Connection test against `GET /v1/projects`
- Toolbar + menu entries: Configuración, Abrir proyecto, Sincronizar
  (last two stubbed — coming in v0.2 and v0.4)
- Build script `scripts/build.sh` producing an installable zip
