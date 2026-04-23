# Pudumaps QGIS Plugin

Official QGIS plugin for [Pudumaps](https://pudumaps.cl) — the Chilean geospatial cloud platform. Browse, pull, push and sync projects and layers between QGIS and your Pudumaps account.

> **Status:** experimental (v0.1.0) · Phase 1 complete · Phase 2 (Open Project) coming soon

## Features

**Available now (v0.1.0)**
- Settings dialog with encrypted API key storage via `QgsAuthManager`
- Connection test against the Pudumaps REST API
- Installable ZIP ready for QGIS 3.22 LTR and later

**Coming in next versions**
- Open a Pudumaps project as QGIS layers (v0.2)
- Upload a QGIS layer to a Pudumaps project (v0.3)
- Bidirectional sync with conflict detection (v0.4)

## Install

1. Download the latest ZIP from the [Releases page](https://github.com/DanielD-S/pudumaps-qgis-plugin/releases)
2. In QGIS: **Plugins → Manage and Install Plugins → Install from ZIP**
3. Select the downloaded ZIP
4. Open **Pudumaps → Configuración** from the plugin menu and paste your API key

## Get an API key

1. Sign up / log in at [pudumaps.cl](https://pudumaps.cl)
2. Upgrade to **Pro** (API access requires Pro plan or higher)
3. Go to **Configuración → API → Nueva key**
4. Copy the key (shown only once) and paste it into the plugin settings

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
# → dist/pudumaps-qgis-0.1.0.zip
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
