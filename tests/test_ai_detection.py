"""Tests del módulo de detección de dependencias IA (pudumaps_qgis.ai).

No requieren tener geoai/GeoAgent instalados — usan monkeypatch sobre
importlib para simular ambos escenarios.
"""

from __future__ import annotations

import importlib
import sys
import types

import pytest

from pudumaps_qgis import ai


def test_module_exports_pinned_versions():
    """Las constantes de versión deben existir y ser strings semver-like."""
    assert isinstance(ai.GEOAI_PINNED_VERSION, str)
    assert isinstance(ai.GEOAGENT_PINNED_VERSION, str)
    # Sanidad mínima: "X.Y.Z" con X,Y,Z numéricos.
    for v in (ai.GEOAI_PINNED_VERSION, ai.GEOAGENT_PINNED_VERSION):
        parts = v.split(".")
        assert len(parts) >= 2
        assert all(p.isdigit() for p in parts[:3])


def test_package_vs_import_names():
    """El nombre PyPI puede diferir del nombre de import (caso geoai-py vs geoai)."""
    assert ai.GEOAI_PACKAGE == "geoai-py"
    assert ai.GEOAI_IMPORT == "geoai"
    assert ai.GEOAGENT_PACKAGE == "GeoAgent"
    assert ai.GEOAGENT_IMPORT == "geoagent"


def test_qgis_python_executable_returns_sys_executable():
    """Debe apuntar al Python actual, no hardcodear paths."""
    assert ai.qgis_python_executable() == sys.executable


def test_is_geoai_available_false_when_missing(monkeypatch):
    """Si find_spec devuelve None, no está disponible."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert ai.is_geoai_available() is False
    assert ai.is_geoagent_available() is False


def test_is_geoai_available_true_when_present(monkeypatch):
    """Si find_spec devuelve un spec, sí está disponible."""

    def fake_find_spec(name: str):
        if name in (ai.GEOAI_IMPORT, ai.GEOAGENT_IMPORT):
            # Cualquier objeto no-None sirve para simular "encontrado".
            return object()
        return None

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    assert ai.is_geoai_available() is True
    assert ai.is_geoagent_available() is True


def test_geoai_version_returns_none_when_not_importable(monkeypatch):
    """Si import falla, version() devuelve None sin lanzar."""

    def raise_import(name: str):
        raise ImportError(name)

    monkeypatch.setattr(importlib, "import_module", raise_import)
    assert ai.geoai_version() is None
    assert ai.geoagent_version() is None


def test_geoai_version_reads_dunder(monkeypatch):
    """Si el módulo expone __version__, lo lee."""
    fake_geoai = types.ModuleType("geoai")
    fake_geoai.__version__ = "0.10.0"
    fake_geoagent = types.ModuleType("geoagent")
    fake_geoagent.__version__ = "0.4.0"

    def import_module(name: str):
        if name == "geoai":
            return fake_geoai
        if name == "geoagent":
            return fake_geoagent
        raise ImportError(name)

    monkeypatch.setattr(importlib, "import_module", import_module)
    assert ai.geoai_version() == "0.10.0"
    assert ai.geoagent_version() == "0.4.0"


def test_matches_pin_true_when_versions_align(monkeypatch):
    """matches_pin() compara con la constante pineada del módulo."""
    fake_geoai = types.ModuleType("geoai")
    fake_geoai.__version__ = ai.GEOAI_PINNED_VERSION
    fake_geoagent = types.ModuleType("geoagent")
    fake_geoagent.__version__ = ai.GEOAGENT_PINNED_VERSION

    def import_module(name: str):
        if name == "geoai":
            return fake_geoai
        if name == "geoagent":
            return fake_geoagent
        raise ImportError(name)

    monkeypatch.setattr(importlib, "import_module", import_module)
    assert ai.geoai_matches_pin() is True
    assert ai.geoagent_matches_pin() is True


def test_matches_pin_false_on_mismatch(monkeypatch):
    """Si la versión instalada difiere del pin, matches_pin() es False."""
    fake_geoai = types.ModuleType("geoai")
    fake_geoai.__version__ = "0.0.1"  # claramente no es la pineada

    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: fake_geoai if name == "geoai" else (_ for _ in ()).throw(ImportError(name)),
    )
    assert ai.geoai_matches_pin() is False


def test_geoai_version_returns_none_for_nonstring_dunder(monkeypatch):
    """Si __version__ no es str (ej. tupla), devolvemos None defensivamente."""
    fake = types.ModuleType("geoai")
    fake.__version__ = (0, 10, 0)  # type: ignore[assignment]

    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: fake if name == "geoai" else (_ for _ in ()).throw(ImportError(name)),
    )
    assert ai.geoai_version() is None
