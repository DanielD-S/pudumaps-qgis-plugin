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
EXCLUDED_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_FILES = {".DS_Store", "Thumbs.db"}


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
