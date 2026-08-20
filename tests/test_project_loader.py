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
    build_arcgis_feature_uri,
    external_layer_to_qgis,
    has_arcgis_layer_index,
    infer_geometry_type,
    parse_wms_external_url,
    resolve_arcgis_feature_url,
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


# ── arcgis_feature: forma del URI ─────────────────────────────────────────
#
# Bug reportado 2026-08-20: 3 capas arcgis_feature fallaban con
# external_layer_invalid aunque los servicios respondían 200 por HTTP.
# Dos causas independientes, ambas verificadas contra QGIS 3.40.9 real:
#   1. El proveedor arcgisfeatureserver rechaza una URL pelada; necesita
#      pares clave=valor con crs y url.
#   2. Rechaza un /FeatureServer sin id de capa. Pudumaps guarda el
#      external_url unas veces con id y otras sin él.


def test_has_arcgis_layer_index_detecta_el_id_final():
    base = "https://example.com/arcgis/rest/services/Foo/FeatureServer"
    assert has_arcgis_layer_index(f"{base}/0")
    assert has_arcgis_layer_index(f"{base}/2")
    assert has_arcgis_layer_index(f"{base}/12/")
    assert not has_arcgis_layer_index(base)
    assert not has_arcgis_layer_index(f"{base}/")
    assert not has_arcgis_layer_index("")


def test_resolve_no_toca_una_url_que_ya_trae_id():
    """Con id no debe salir a la red: el fetcher explota si lo llaman."""

    def boom(_url):
        raise AssertionError("no debería consultar metadata si ya hay id")

    url = "https://example.com/arcgis/rest/services/Foo/FeatureServer/2"
    assert resolve_arcgis_feature_url(url, fetch_json=boom) == url


def test_resolve_toma_la_primera_capa_del_servicio():
    base = "https://example.com/arcgis/rest/services/Foo/FeatureServer"
    meta = {"layers": [{"id": 3, "name": "Algo"}, {"id": 4, "name": "Otro"}]}
    assert resolve_arcgis_feature_url(base, fetch_json=lambda _u: meta) == f"{base}/3"


def test_resolve_cae_a_cero_si_la_metadata_falla():
    """Servicio caído o JSON raro no debe romper la carga: se asume capa 0."""
    base = "https://example.com/arcgis/rest/services/Foo/FeatureServer"

    def boom(_url):
        raise RuntimeError("503")

    assert resolve_arcgis_feature_url(base, fetch_json=boom) == f"{base}/0"


def test_resolve_cae_a_cero_si_el_servicio_no_declara_capas():
    base = "https://example.com/arcgis/rest/services/Foo/FeatureServer"
    assert resolve_arcgis_feature_url(base, fetch_json=lambda _u: {}) == f"{base}/0"


def test_resolve_normaliza_la_barra_final():
    base = "https://example.com/arcgis/rest/services/Foo/FeatureServer"
    meta = {"layers": [{"id": 0}]}
    assert resolve_arcgis_feature_url(f"{base}/", fetch_json=lambda _u: meta) == f"{base}/0"


def test_build_uri_usa_pares_clave_valor_no_url_pelada():
    """La URL pelada es justamente lo que el proveedor rechazaba."""
    url = "https://example.com/arcgis/rest/services/Foo/FeatureServer/2"
    uri = build_arcgis_feature_uri(url, fetch_json=lambda _u: {})
    assert uri == f"crs='EPSG:4326' url='{url}'"
    assert uri != url


def test_external_layer_to_qgis_arcgis_feature_uses_vector_provider(monkeypatch):
    monkeypatch.setattr(project_loader, "QgsVectorLayer", _FakeQgisLayer)
    url = "https://example.com/arcgis/rest/services/Foo/FeatureServer/0"
    layer = external_layer_to_qgis("arcgis_feature", url, "Foo")
    assert layer.provider == "arcgisfeatureserver"
    # Antes se pasaba `url` tal cual y el proveedor lo rechazaba en silencio.
    assert layer.uri == f"crs='EPSG:4326' url='{url}'"


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
