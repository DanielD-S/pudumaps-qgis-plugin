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
from pudumaps_qgis.ai.tools.extract_buildings import ExtractBuildingsTool


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
