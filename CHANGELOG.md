# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] — 2026-04-23

### Added
- **Open a Pudumaps project as QGIS layers (pull)**
- Projects dialog with list of all your projects (name, description, created)
- Automatic layer group `Pudumaps: <project name>` in the layer tree
- Basic default styling (green points/lines/polygons) applied to each loaded layer
- Progress bar during multi-layer pull
- Remote project/layer ids stamped as custom properties (`pudumaps/layer_id`,
  `pudumaps/project_id`) for future push/sync
- Per-layer error isolation — one failed layer doesn't abort the whole import

### Changed
- "Abrir proyecto" toolbar action now opens the projects dialog instead of
  the "coming soon" placeholder

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
