"""Tests for the pure-Python parts of project_loader.

Anything touching QgsVectorLayer/QgsProject requires a running QGIS env
and is validated manually during the Phase 2 test plan instead.
"""

from __future__ import annotations

import sys
from types import ModuleType


def _stub_qgis_core() -> None:
    """project_loader imports qgis.core at module top-level. Stub the
    classes it uses so we can test the pure helpers without a QGIS runtime.
    """
    qgis = ModuleType("qgis")
    core = ModuleType("qgis.core")

    class _Stub:
        @staticmethod
        def createSimple(*_a, **_kw):
            return object()

    for name in (
        "QgsFillSymbol",
        "QgsLineSymbol",
        "QgsMarkerSymbol",
        "QgsProject",
        "QgsSingleSymbolRenderer",
        "QgsVectorLayer",
        "QgsWkbTypes",
        "QgsRectangle",
    ):
        setattr(core, name, _Stub)

    qgis.core = core
    sys.modules.setdefault("qgis", qgis)
    sys.modules["qgis.core"] = core


_stub_qgis_core()

from pudumaps_qgis.project_loader import (  # noqa: E402
    _field_type_for,
    _safe_field_name,
    infer_geometry_type,
)


def test_infer_point_from_feature_collection():
    gj = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}}
        ],
    }
    assert infer_geometry_type(gj) == "Point"


def test_infer_polygon_skips_null_geometry_before_real_one():
    gj = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": None},
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            },
        ],
    }
    assert infer_geometry_type(gj) == "Polygon"


def test_infer_single_feature_input():
    gj = {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
    }
    assert infer_geometry_type(gj) == "LineString"


def test_infer_empty_fc_falls_back_to_multipolygon():
    assert infer_geometry_type({"type": "FeatureCollection", "features": []}) == "MultiPolygon"


def test_infer_unsupported_type_falls_back():
    gj = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": {"type": "GeometryCollection"}}],
    }
    assert infer_geometry_type(gj) == "MultiPolygon"


def test_safe_field_name_handles_special_chars():
    assert _safe_field_name("Nombre Calle") == "Nombre_Calle"
    assert _safe_field_name("id-001") == "id_001"
    assert _safe_field_name("") == "field"
    # Unicode letters (incluida la ñ) son válidos en Python isalnum()
    # y QGIS los acepta. Solo reemplazamos espacios y símbolos.
    assert _safe_field_name("año") == "año"
    assert _safe_field_name("mes/año") == "mes_año"


def test_field_type_mapping_covers_common_types():
    # QVariant.Int=2 / Double=6 / String=10
    assert _field_type_for(2) == "integer"
    assert _field_type_for(6) == "double"
    assert _field_type_for(10) == "string"
    assert _field_type_for(999) == "string"  # unknown → string fallback
