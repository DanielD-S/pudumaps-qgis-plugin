#!/usr/bin/env python3
"""Package the plugin as a zip ready for QGIS "Install from ZIP".

Cross-platform alternative to build.sh — uses only stdlib so it works on
Windows (no need for the `zip` binary).

Usage:
    python scripts/build.py
    python scripts/build.py --version  # just prints the version
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "pudumaps_qgis"
DIST_DIR = ROOT / "dist"
EXCLUDED_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", "ai"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_FILES = {".DS_Store", "Thumbs.db"}
# Diálogos IA: viven en dialogs/ (no en ai/, que ya se excluye arriba) e
# importan de ese paquete, así que se excluyen aparte para no romper el
# zip publicado. El módulo IA queda fuera del build hasta que se retome.
EXCLUDED_RELATIVE_FILES = {
    Path("pudumaps_qgis/dialogs/ai_panel.py"),
    Path("pudumaps_qgis/dialogs/install_ai_dialog.py"),
    Path("pudumaps_qgis/dialogs/change_detection_dialog.py"),
    Path("pudumaps_qgis/dialogs/download_sentinel_dialog.py"),
    Path("pudumaps_qgis/icons/ai.svg"),
}


def read_version() -> str:
    meta = (SRC_DIR / "metadata.txt").read_text(encoding="utf-8")
    for line in meta.splitlines():
        if line.strip().startswith("version="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("version= not found in metadata.txt")


def should_skip(path: Path) -> bool:
    if path.name in EXCLUDED_FILES:
        return True
    if path.suffix in EXCLUDED_SUFFIXES:
        return True
    if path.relative_to(ROOT) in EXCLUDED_RELATIVE_FILES:
        return True
    return any(part in EXCLUDED_DIRS for part in path.parts)


def build() -> Path:
    version = read_version()
    DIST_DIR.mkdir(exist_ok=True)
    zip_path = DIST_DIR / f"pudumaps-qgis-{version}.zip"
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in SRC_DIR.rglob("*"):
            if file.is_dir() or should_skip(file):
                continue
            arcname = file.relative_to(ROOT)
            zf.write(file, arcname)

        # plugins.qgis.org exige un LICENSE dentro del paquete (junto a
        # metadata.txt) — el nuestro vive en la raíz del repo, no en
        # pudumaps_qgis/, así que el loop de arriba nunca lo agarra.
        license_file = ROOT / "LICENSE"
        if not license_file.exists():
            raise RuntimeError("LICENSE no encontrado en la raíz del repo")
        zf.write(license_file, SRC_DIR.name + "/LICENSE")

    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", action="store_true", help="print version and exit")
    args = parser.parse_args()
    if args.version:
        print(read_version())
        return 0

    zip_path = build()
    print(f"[OK] Built {zip_path}")
    print("   Install in QGIS: Plugins -> Manage and Install Plugins -> Install from ZIP")
    return 0


if __name__ == "__main__":
    sys.exit(main())
