"""Tests del framework de tools IA (base, registry, extract_buildings).

No requieren QGIS ni geoai instalados. Usan duck-typed fakes para las
capas y mockean importlib donde corresponda.
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import types
from typing import Optional
from unittest.mock import patch

import pytest

from pudumaps_qgis.ai.tools import AITool, AIToolError, AIToolUnavailable
from pudumaps_qgis.ai.tools import registry as registry_mod
from pudumaps_qgis.ai.tools.change_detection import ChangeDetectionTool
from pudumaps_qgis.ai.tools.download_sentinel import DownloadSentinelTool
from pudumaps_qgis.ai.tools.extract_buildings import ExtractBuildingsTool
from pudumaps_qgis.ai.tools.extract_water import ExtractWaterTool
from pudumaps_qgis.ai.tools.landcover_classification import LandCoverClassificationTool


# ── Helpers / fakes ──────────────────────────────────────────────────────


class _FakeRasterLayer:
    """Mínimo de la API de QgsRasterLayer que validate_input toca."""

    def __init__(self, band_count: int = 3, source: str = "/tmp/r.tif"):
        self._band_count = band_count
        self._source = source

    def bandCount(self) -> int:
        return self._band_count

    def source(self) -> str:
        return self._source


class _FakeVectorLayer:
    """Vector layer mínimo — sin bandCount, como QgsVectorLayer real."""

    def source(self) -> str:
        return "/tmp/v.geojson"


# ── Base / contract ──────────────────────────────────────────────────────


def test_aitool_is_abstract():
    """No se puede instanciar AITool directamente."""
    with pytest.raises(TypeError):
        AITool()  # type: ignore[abstract]


def test_aitool_subclass_must_implement_run_and_validate():
    """Subclase sin métodos abstractos también falla al instanciar."""

    class Incomplete(AITool):
        id = "x"
        name = "X"
        requires = []

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def test_aitool_is_available_with_empty_requires():
    """Sin requires, una tool siempre está disponible."""

    class NoReq(AITool):
        id = "noreq"
        name = "NoReq"
        requires = []

        def validate_input(self, layer):
            return None

        def run(self, raster_path, output_path, params=None, progress_cb=None):
            return output_path

    assert NoReq.is_available() is True
    assert NoReq.missing_requirements() == []


def test_aitool_missing_requirements_lists_uninstalled(monkeypatch):
    """missing_requirements() devuelve los que find_spec dice que no están."""

    class NeedsBoth(AITool):
        id = "x"
        name = "X"
        requires = ["geoai", "geoagent"]

        def validate_input(self, layer):
            return None

        def run(self, raster_path, output_path, params=None, progress_cb=None):
            return output_path

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert NeedsBoth.is_available() is False
    assert set(NeedsBoth.missing_requirements()) == {"geoai", "geoagent"}


def test_aitool_ensure_available_raises_when_missing(monkeypatch):
    """ensure_available() levanta AIToolUnavailable con mensaje legible."""

    class NeedsGeoai(AITool):
        id = "x"
        name = "X"
        requires = ["geoai"]

        def validate_input(self, layer):
            return None

        def run(self, raster_path, output_path, params=None, progress_cb=None):
            return output_path

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    with pytest.raises(AIToolUnavailable) as exc:
        NeedsGeoai().ensure_available()
    assert "geoai" in str(exc.value)


# ── Registry ─────────────────────────────────────────────────────────────


def test_registry_lists_at_least_one_tool():
    tools = registry_mod.get_tools()
    assert len(tools) >= 1


def test_registry_tool_ids_are_unique():
    ids = registry_mod.tool_ids()
    assert len(ids) == len(set(ids)), f"IDs duplicadas: {ids}"


def test_registry_get_tool_by_id():
    """get_tool('extract_buildings') devuelve una instancia válida."""
    tool = registry_mod.get_tool("extract_buildings")
    assert tool is not None
    assert isinstance(tool, AITool)
    assert tool.id == "extract_buildings"


def test_registry_get_tool_unknown_returns_none():
    assert registry_mod.get_tool("xxx-no-existe") is None


def test_registry_tools_have_required_fields():
    """Toda tool registrada debe tener id, name, description no vacíos."""
    for tool in registry_mod.get_tools():
        assert tool.id, f"Tool sin id: {type(tool).__name__}"
        assert tool.name, f"Tool sin name: {tool.id}"
        assert tool.description, f"Tool sin description: {tool.id}"


# ── ExtractBuildingsTool ─────────────────────────────────────────────────


def test_extract_buildings_rejects_none_layer():
    msg = ExtractBuildingsTool().validate_input(None)
    assert msg is not None
    assert "capa" in msg.lower()


def test_extract_buildings_rejects_vector_layer():
    msg = ExtractBuildingsTool().validate_input(_FakeVectorLayer())
    assert msg is not None
    assert "raster" in msg.lower() or "vectorial" in msg.lower()


def test_extract_buildings_rejects_single_band_raster():
    msg = ExtractBuildingsTool().validate_input(_FakeRasterLayer(band_count=1))
    assert msg is not None
    assert "3" in msg  # menciona el mínimo


def test_extract_buildings_accepts_3band_raster():
    msg = ExtractBuildingsTool().validate_input(_FakeRasterLayer(band_count=3))
    assert msg is None


def test_extract_buildings_accepts_4band_raster():
    msg = ExtractBuildingsTool().validate_input(_FakeRasterLayer(band_count=4))
    assert msg is None


def test_extract_buildings_rejects_raster_without_source():
    msg = ExtractBuildingsTool().validate_input(_FakeRasterLayer(source=""))
    assert msg is not None


def test_extract_buildings_run_without_geoai_raises_unavailable(monkeypatch):
    """run() debe abortar limpio si geoai no está instalado."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    tool = ExtractBuildingsTool()
    with pytest.raises(AIToolUnavailable):
        tool.run(
            raster_path="/no-importa.tif",
            output_path="/no-importa.geojson",
        )


def test_extract_buildings_run_with_missing_raster_raises(monkeypatch):
    """Si el raster no existe en disco, error claro."""
    # Simular geoai instalado.
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())

    tool = ExtractBuildingsTool()
    with pytest.raises(AIToolError) as exc:
        tool.run(
            raster_path="/no-existe-en-este-disco.tif",
            output_path=os.path.join(tempfile.gettempdir(), "out.geojson"),
        )
    assert "No existe" in str(exc.value)


def test_extract_buildings_id_is_stable():
    """El id se usa como key en logs y settings — no debe cambiar entre versiones
    sin coordinarlo (rompería settings persistidos)."""
    assert ExtractBuildingsTool.id == "extract_buildings"
    assert ExtractBuildingsTool.input_kind == "raster"
    assert "geoai" in ExtractBuildingsTool.requires


# ── ExtractWaterTool ─────────────────────────────────────────────────────


def test_extract_water_rejects_none_layer():
    msg = ExtractWaterTool().validate_input(None)
    assert msg is not None
    assert "capa" in msg.lower()


def test_extract_water_rejects_vector_layer():
    msg = ExtractWaterTool().validate_input(_FakeVectorLayer())
    assert msg is not None
    assert "raster" in msg.lower() or "vectorial" in msg.lower()


def test_extract_water_rejects_single_band_raster():
    msg = ExtractWaterTool().validate_input(_FakeRasterLayer(band_count=1))
    assert msg is not None
    assert "3" in msg


def test_extract_water_accepts_3band_raster():
    msg = ExtractWaterTool().validate_input(_FakeRasterLayer(band_count=3))
    assert msg is None


def test_extract_water_run_without_geoai_raises_unavailable(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    tool = ExtractWaterTool()
    with pytest.raises(AIToolUnavailable):
        tool.run(
            raster_path="/no-importa.tif",
            output_path="/no-importa.geojson",
        )


def test_extract_water_run_with_missing_raster_raises(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    tool = ExtractWaterTool()
    with pytest.raises(AIToolError) as exc:
        tool.run(
            raster_path="/no-existe-en-este-disco.tif",
            output_path=os.path.join(tempfile.gettempdir(), "out.geojson"),
        )
    assert "No existe" in str(exc.value)


def test_extract_water_id_is_stable():
    assert ExtractWaterTool.id == "extract_water"
    assert ExtractWaterTool.input_kind == "raster"
    assert "geoai" in ExtractWaterTool.requires


# ── Registry incluye ambas tools ─────────────────────────────────────────


def test_registry_includes_water_and_buildings():
    ids = registry_mod.tool_ids()
    assert "extract_buildings" in ids
    assert "extract_water" in ids


# ── LandCoverClassificationTool ──────────────────────────────────────────


def test_landcover_id_and_output_suffix():
    """Landcover produce raster .tif, no GeoJSON."""
    assert LandCoverClassificationTool.id == "landcover_classification"
    assert LandCoverClassificationTool.output_suffix == ".tif"
    assert LandCoverClassificationTool.input_kind == "raster"
    assert "geoai" in LandCoverClassificationTool.requires


def test_landcover_rejects_none_layer():
    msg = LandCoverClassificationTool().validate_input(None)
    assert msg is not None


def test_landcover_rejects_vector_layer():
    msg = LandCoverClassificationTool().validate_input(_FakeVectorLayer())
    assert msg is not None


def test_landcover_rejects_single_band_raster():
    msg = LandCoverClassificationTool().validate_input(_FakeRasterLayer(band_count=1))
    assert msg is not None
    assert "3" in msg


def test_landcover_accepts_3band_raster():
    msg = LandCoverClassificationTool().validate_input(_FakeRasterLayer(band_count=3))
    assert msg is None


def test_landcover_run_without_geoai_raises_unavailable(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    tool = LandCoverClassificationTool()
    with pytest.raises(AIToolUnavailable):
        tool.run(
            raster_path="/no-importa.tif",
            output_path="/no-importa.tif",
        )


def test_landcover_run_with_missing_raster_raises(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    tool = LandCoverClassificationTool()
    with pytest.raises(AIToolError) as exc:
        tool.run(
            raster_path="/no-existe.tif",
            output_path=os.path.join(tempfile.gettempdir(), "out.tif"),
        )
    assert "No existe" in str(exc.value)


def test_registry_includes_landcover():
    assert "landcover_classification" in registry_mod.tool_ids()


# ── Default output_suffix is .geojson for back-compat ────────────────────


def test_default_output_suffix_is_geojson():
    """Buildings y water no declaran output_suffix → heredan .geojson."""
    assert ExtractBuildingsTool.output_suffix == ".geojson"
    assert ExtractWaterTool.output_suffix == ".geojson"


# ── input_kind="none" hook + prompt_params() default ─────────────────────


def test_base_prompt_params_default_returns_empty_dict():
    """Tools simples no necesitan override; el default `{}` los deja pasar."""
    assert ExtractBuildingsTool().prompt_params() == {}
    assert ExtractWaterTool().prompt_params() == {}
    assert LandCoverClassificationTool().prompt_params() == {}


# ── ChangeDetectionTool ──────────────────────────────────────────────────


def test_change_detection_input_kind_is_none():
    """No usa capa activa — todo viene de prompt_params."""
    assert ChangeDetectionTool.input_kind == "none"
    assert ChangeDetectionTool.output_suffix == ".tif"
    assert ChangeDetectionTool.id == "change_detection"


def test_change_detection_validate_input_always_ok():
    """Con input_kind='none', validate_input no rechaza nada."""
    tool = ChangeDetectionTool()
    assert tool.validate_input(None) is None
    assert tool.validate_input(_FakeRasterLayer()) is None
    assert tool.validate_input(_FakeVectorLayer()) is None


def test_change_detection_run_requires_both_paths(monkeypatch):
    """Si faltan raster_before o raster_after en params, error claro."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    tool = ChangeDetectionTool()
    with pytest.raises(AIToolError) as exc:
        tool.run(
            raster_path="",
            output_path="/tmp/out.tif",
            params={},
        )
    assert "raster_before" in str(exc.value)


def test_change_detection_run_rejects_same_raster(monkeypatch, tmp_path):
    """Pasar el mismo path como antes y después se rechaza."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    raster = tmp_path / "r.tif"
    raster.write_bytes(b"")
    tool = ChangeDetectionTool()
    with pytest.raises(AIToolError) as exc:
        tool.run(
            raster_path="",
            output_path=str(tmp_path / "out.tif"),
            params={"raster_before": str(raster), "raster_after": str(raster)},
        )
    assert "mismo" in str(exc.value).lower()


def test_change_detection_run_rejects_missing_raster(monkeypatch, tmp_path):
    """Si uno de los paths no existe en disco, error específico."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    raster_a = tmp_path / "a.tif"
    raster_a.write_bytes(b"")
    tool = ChangeDetectionTool()
    with pytest.raises(AIToolError) as exc:
        tool.run(
            raster_path="",
            output_path=str(tmp_path / "out.tif"),
            params={
                "raster_before": str(raster_a),
                "raster_after": "/no-existe.tif",
            },
        )
    assert "después" in str(exc.value)


def test_change_detection_run_without_geoai_raises_unavailable(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    with pytest.raises(AIToolUnavailable):
        ChangeDetectionTool().run(
            raster_path="",
            output_path="/tmp/out.tif",
            params={"raster_before": "/a.tif", "raster_after": "/b.tif"},
        )


def test_registry_includes_change_detection():
    assert "change_detection" in registry_mod.tool_ids()


# ── DownloadSentinelTool ─────────────────────────────────────────────────


def test_download_sentinel_metadata():
    assert DownloadSentinelTool.id == "download_sentinel"
    assert DownloadSentinelTool.input_kind == "none"
    assert DownloadSentinelTool.output_suffix == ".tif"
    assert "geoai" in DownloadSentinelTool.requires


def test_download_sentinel_validate_input_always_ok():
    """input_kind='none' → validate_input no rechaza nada."""
    tool = DownloadSentinelTool()
    assert tool.validate_input(None) is None
    assert tool.validate_input(_FakeRasterLayer()) is None


def test_download_sentinel_run_requires_bbox(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    tool = DownloadSentinelTool()
    with pytest.raises(AIToolError) as exc:
        tool.run(
            raster_path="",
            output_path="/tmp/out.tif",
            params={"date_start": "2024-01-01", "date_end": "2024-01-30"},
        )
    assert "bbox" in str(exc.value).lower()


def test_download_sentinel_run_rejects_invalid_bbox(monkeypatch):
    """xmin >= xmax debe rechazarse con mensaje claro."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    tool = DownloadSentinelTool()
    with pytest.raises(AIToolError) as exc:
        tool.run(
            raster_path="",
            output_path="/tmp/out.tif",
            params={
                "bbox": (-70, -33, -71, -32),  # xmin > xmax
                "date_start": "2024-01-01",
                "date_end": "2024-01-30",
                "cloud_max": 20,
            },
        )
    assert "inválido" in str(exc.value).lower()


def test_download_sentinel_run_rejects_huge_bbox(monkeypatch):
    """bbox >5° en ancho/alto se rechaza para evitar descargas masivas."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    tool = DownloadSentinelTool()
    with pytest.raises(AIToolError) as exc:
        tool.run(
            raster_path="",
            output_path="/tmp/out.tif",
            params={
                "bbox": (-75, -45, -65, -25),  # 10° ancho, 20° alto
                "date_start": "2024-01-01",
                "date_end": "2024-01-30",
                "cloud_max": 20,
            },
        )
    assert "grande" in str(exc.value).lower()


def test_download_sentinel_run_rejects_inverted_dates(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    tool = DownloadSentinelTool()
    with pytest.raises(AIToolError) as exc:
        tool.run(
            raster_path="",
            output_path="/tmp/out.tif",
            params={
                "bbox": (-70.7, -33.5, -70.6, -33.4),
                "date_start": "2024-06-01",
                "date_end": "2024-01-01",
                "cloud_max": 20,
            },
        )
    assert "anterior" in str(exc.value).lower()


def test_download_sentinel_run_rejects_pre_sentinel_era(monkeypatch):
    """Fechas antes del 2015-06-23 (launch S-2A) deben rechazarse."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    tool = DownloadSentinelTool()
    with pytest.raises(AIToolError) as exc:
        tool.run(
            raster_path="",
            output_path="/tmp/out.tif",
            params={
                "bbox": (-70.7, -33.5, -70.6, -33.4),
                "date_start": "2010-01-01",
                "date_end": "2010-06-01",
                "cloud_max": 20,
            },
        )
    assert "2015" in str(exc.value)


def test_download_sentinel_run_rejects_cloud_max_out_of_range(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    tool = DownloadSentinelTool()
    with pytest.raises(AIToolError) as exc:
        tool.run(
            raster_path="",
            output_path="/tmp/out.tif",
            params={
                "bbox": (-70.7, -33.5, -70.6, -33.4),
                "date_start": "2024-01-01",
                "date_end": "2024-01-30",
                "cloud_max": 200,
            },
        )
    assert "100" in str(exc.value)


def test_download_sentinel_run_without_geoai_raises_unavailable(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    with pytest.raises(AIToolUnavailable):
        DownloadSentinelTool().run(
            raster_path="",
            output_path="/tmp/out.tif",
            params={
                "bbox": (-70.7, -33.5, -70.6, -33.4),
                "date_start": "2024-01-01",
                "date_end": "2024-01-30",
                "cloud_max": 20,
            },
        )


def test_registry_includes_download_sentinel():
    assert "download_sentinel" in registry_mod.tool_ids()


def test_registry_has_all_five_actions():
    """Cierre del ciclo IA v0.7.x: las 5 acciones del plan original."""
    ids = set(registry_mod.tool_ids())
    expected = {
        "extract_buildings",
        "extract_water",
        "landcover_classification",
        "change_detection",
        "download_sentinel",
    }
    assert expected.issubset(ids)
