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
        "QgsMapLayer",
        "QgsMarkerSymbol",
        "QgsProject",
        "QgsRasterLayer",
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

import pytest  # noqa: E402

import pudumaps_qgis.project_loader as project_loader  # noqa: E402
from pudumaps_qgis.project_loader import (  # noqa: E402
    EXTERNAL_LAYER_TYPES,
    InvalidExternalLayerError,
    UnsupportedLayerError,
    _field_type_for,
    _safe_field_name,
    external_layer_to_qgis,
    infer_geometry_type,
    parse_wms_external_url,
)


class _FakeQgisLayer:
    """Sustituye QgsRasterLayer/QgsVectorLayer para inspeccionar con qué
    URI/proveedor external_layer_to_qgis los construyó, sin depender de un
    runtime QGIS real."""

    def __init__(self, uri, name, provider):
        self.uri = uri
        self.name = name
        self.provider = provider

    def isValid(self):
        return True


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


# ── Capas externas (wms/arcgis_map/arcgis_feature/weather) ─────────────────


def test_external_layer_types_matches_db_check_constraint():
    # Espeja el CHECK constraint de project_layers — si alguien agrega un
    # layer_type nuevo en la DB (20260424130000_project_layers_external.sql)
    # sin actualizar acá, este test lo marca.
    assert EXTERNAL_LAYER_TYPES == {"wms", "arcgis_map", "arcgis_feature", "weather"}


def test_parse_wms_external_url_splits_base_and_decodes_layers():
    base, layers = parse_wms_external_url(
        "wms://ide.minagri.gob.cl/geoserver/wms?layers=namespace%3Auso_suelo"
    )
    assert base == "ide.minagri.gob.cl/geoserver/wms"
    assert layers == "namespace:uso_suelo"


def test_parse_wms_external_url_tolerates_missing_scheme():
    # La rehidratación JS también aplica el replace de forma tolerante
    # (WMSLayerPanel.tsx) — un external_url sin el prefijo wms:// no debería
    # reventar, solo tratarse como si ya viniera sin prefijo.
    base, layers = parse_wms_external_url("host/wms?layers=foo")
    assert base == "host/wms"
    assert layers == "foo"


def test_parse_wms_external_url_rejects_missing_layers_param():
    with pytest.raises(InvalidExternalLayerError):
        parse_wms_external_url("wms://host/wms")


def test_parse_wms_external_url_rejects_empty_layers_value():
    with pytest.raises(InvalidExternalLayerError):
        parse_wms_external_url("wms://host/wms?layers=")


def test_external_layer_to_qgis_wms_builds_ogc_wms_uri(monkeypatch):
    monkeypatch.setattr(project_loader, "QgsRasterLayer", _FakeQgisLayer)
    layer = external_layer_to_qgis(
        "wms", "wms://host/geoserver/wms?layers=ns%3Acapa", "Mi capa"
    )
    assert layer.provider == "wms"
    assert layer.uri == "crs=EPSG:4326&format=image/png&layers=ns:capa&styles=&url=host/geoserver/wms"


def test_external_layer_to_qgis_arcgis_map_uses_rest_url_directly(monkeypatch):
    monkeypatch.setattr(project_loader, "QgsRasterLayer", _FakeQgisLayer)
    url = "https://example.com/arcgis/rest/services/Foo/MapServer"
    layer = external_layer_to_qgis("arcgis_map", url, "Foo")
    assert layer.provider == "arcgismapserver"
    assert layer.uri == url


def test_external_layer_to_qgis_arcgis_feature_uses_vector_provider(monkeypatch):
    monkeypatch.setattr(project_loader, "QgsVectorLayer", _FakeQgisLayer)
    url = "https://example.com/arcgis/rest/services/Foo/FeatureServer/0"
    layer = external_layer_to_qgis("arcgis_feature", url, "Foo")
    assert layer.provider == "arcgisfeatureserver"
    assert layer.uri == url


def test_external_layer_to_qgis_weather_is_unsupported_not_invalid():
    # 'weather' no tiene URL real (weather://<variable> es un sentinel del
    # frontend, sin servicio geoespacial detrás) — debe ser
    # UnsupportedLayerError, no InvalidExternalLayerError, para que el
    # caller lo reporte como "no soportado" y no como bug/dato corrupto.
    with pytest.raises(UnsupportedLayerError):
        external_layer_to_qgis("weather", "weather://temperature", "Clima")


def test_external_layer_to_qgis_missing_url_is_invalid():
    with pytest.raises(InvalidExternalLayerError):
        external_layer_to_qgis("wms", "", "Sin URL")


def test_external_layer_to_qgis_unknown_type_is_unsupported():
    with pytest.raises(UnsupportedLayerError):
        external_layer_to_qgis("something_new", "https://example.com", "Rara")
