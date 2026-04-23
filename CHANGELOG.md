# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.3.0] — 2026-04-23

### Added
- **Upload a QGIS layer to Pudumaps (push)** via two entry points:
  - Right-click on a vector layer in the Layers Panel → *Subir a Pudumaps…*
  - Menu/toolbar action *Subir capa activa a Pudumaps…*
- `UploadLayerDialog`: dropdown of user's projects + *Nuevo…* button to
  create a project inline without leaving QGIS
- `exporter.layer_to_geojson()`: serializes a `QgsVectorLayer` to a
  GeoJSON FeatureCollection with automatic reprojection to EPSG:4326
  when the source CRS is different (PSAD56, UTM19S, etc.)
- Pre-upload validation: 10 MB body cap (matches API limit),
  20,000-feature max (matches `validateGeoJSON` limit)
- Smart dispatch: layers that originated from a Pudumaps pull (detected
  via the `pudumaps/layer_id` custom property) are **updated in place**
  with PATCH instead of duplicating via POST. First-time uploads stamp
  the returned id on the layer so the next upload becomes an update.

### Changed
- Menu/toolbar now has four actions (previously three) — the new
  upload action sits between *Abrir proyecto* and *Sincronizar*.

## [0.2.1] — 2026-04-23

### Fixed
- Polygon/MultiPolygon layers now render correctly. Previously OGR would
  promote single-geometry features to their Multi- variant when reading
  GeoJSON, and the memory layer created with the inferred `Polygon` URI
  would silently reject `MultiPolygon` features on `addFeatures()`,
  resulting in empty-looking layers in QGIS. Now the memory layer uses
  OGR's actual `wkbType` and inherits the CRS from the OGR layer.
- Fallback to OGR-backed layer when the memory provider rejects the
  features anyway (last-resort robustness).

### Added
- Auto-zoom to the combined extent of the loaded group after pull, so
  layers are immediately visible even when they live far from the
  current map viewport (e.g. Los Ríos region while the canvas was
  showing Europe).

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
