"""Tests for the pure-Python parts of exporter.

QgsVectorLayer-dependent paths (layer_to_geojson) are validated via the
manual test plan in QGIS.
"""

from __future__ import annotations

import sys
from types import ModuleType


def _stub_qgis_core() -> None:
    """exporter imports qgis.core at module top-level. Stub it so we can
    test the pure helpers without a QGIS runtime."""
    qgis = ModuleType("qgis")
    core = ModuleType("qgis.core")

    class _Stub:
        def __init__(self, *a, **kw):
            pass

        def __call__(self, *a, **kw):
            return self

        def __getattr__(self, _name):
            return _Stub()

    for name in (
        "QgsCoordinateReferenceSystem",
        "QgsCoordinateTransform",
        "QgsCoordinateTransformContext",
        "QgsFeature",
        "QgsJsonExporter",
        "QgsProject",
        "QgsVectorLayer",
    ):
        setattr(core, name, _Stub)

    qgis.core = core
    sys.modules.setdefault("qgis", qgis)
    sys.modules["qgis.core"] = core


_stub_qgis_core()

from pudumaps_qgis.exporter import (  # noqa: E402
    MAX_BODY_MB,
    MAX_FEATURE_COUNT,
    TARGET_CRS,
    format_size,
)


def test_format_size_bytes():
    assert format_size(0) == "0 B"
    assert format_size(512) == "512 B"
    assert format_size(1023) == "1023 B"


def test_format_size_kb():
    assert format_size(1024) == "1.0 KB"
    assert format_size(1536) == "1.5 KB"  # 1.5 KB
    assert format_size(1024 * 1023) == "1023.0 KB"


def test_format_size_mb():
    assert format_size(1024 * 1024) == "1.0 MB"
    assert format_size(5 * 1024 * 1024 + 512 * 1024) == "5.5 MB"


def test_constants_match_api_limits():
    # These must match the Edge Function's body guard and validateGeoJSON
    # limits (see supabase/functions/api-v1/index.ts MAX_BODY_BYTES and
    # geovalidate.ts MAX_FEATURES).
    assert MAX_BODY_MB == 10
    assert MAX_FEATURE_COUNT == 20_000
    assert TARGET_CRS == "EPSG:4326"
