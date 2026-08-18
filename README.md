# Pudumaps QGIS Plugin

Official QGIS plugin for [Pudumaps](https://pudumaps.cl) — the Chilean geospatial cloud platform. Browse, pull, push and sync projects and layers between QGIS and your Pudumaps account.

> **Status:** experimental (v0.8.0) — not yet published to plugins.qgis.org

## Features

- Settings dialog with encrypted API key storage via `QgsAuthManager`
- Open a Pudumaps project as QGIS layers (pull), with an automatic layer group per project
- Upload a QGIS vector layer to a Pudumaps project (push), from the menu, toolbar or layer-panel context menu
- Bidirectional sync with per-layer conflict detection (unchanged / local-only / remote-only / conflict / new / deleted)
- Installable ZIP ready for QGIS 3.22 LTR and later

## Install

1. Download the latest ZIP from the [Releases page](https://github.com/DanielD-S/pudumaps-qgis-plugin/releases)
2. In QGIS: **Plugins → Manage and Install Plugins → Install from ZIP**
3. Select the downloaded ZIP
4. Open **Pudumaps → Configuración** from the plugin menu and paste your API key

## Get an API key

1. Sign up / log in at [pudumaps.cl](https://pudumaps.cl) — free plan works
2. Go to **Configuración → API → Nueva key**
3. Copy the key (shown only once) and paste it into the plugin settings

Full API documentation: <https://pudumaps.cl/api-docs.html>

## Development

```bash
# Clone
git clone https://github.com/DanielD-S/pudumaps-qgis-plugin
cd pudumaps-qgis-plugin

# Install dev dependencies (pytest, ruff, black)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# Run tests
pytest

# Lint
ruff check .
black --check .

# Build installable ZIP (cross-platform Python script)
python scripts/build.py
# → dist/pudumaps-qgis-<version>.zip (version read from metadata.txt)
#
# Or on Linux/macOS:
# ./scripts/build.sh
```

## License

GPL-3.0-or-later. See [LICENSE](./LICENSE).

## Links

- Web app: <https://pudumaps.cl>
- API docs (Swagger UI): <https://pudumaps.cl/api-docs.html>
- API reference (Spanish): [docs/api-reference.md](https://github.com/DanielD-S/pudumaps/blob/main/docs/api-reference.md)
- Issues: <https://github.com/DanielD-S/pudumaps-qgis-plugin/issues>
