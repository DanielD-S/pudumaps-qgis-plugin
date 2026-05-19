"""Tests del módulo de detección de dependencias IA (pudumaps_qgis.ai).

No requieren tener geoai/GeoAgent instalados — usan monkeypatch sobre
importlib para simular ambos escenarios.
"""

from __future__ import annotations

import importlib
import os
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
    """Debe apuntar al Python actual, no hardcodear paths.

    Asume entorno de test = python.exe real (no QGIS-Windows). En
    QGIS-Windows este test no aplica — ver tests específicos abajo.
    """
    result = ai.qgis_python_executable()
    # En CI/local debería ser python (no qgis-bin).
    assert "python" in result.lower() or result == sys.executable


def test_qgis_python_executable_windows_qgis_uses_sys_prefix(monkeypatch, tmp_path):
    """En Windows + sys.executable=qgis-bin.exe debe derivar python.exe
    desde sys.prefix (donde QGIS embebe el Python).

    Reproduce el bug reportado en 0.7.6: subprocess relanzaba QGIS porque
    sys.executable apuntaba a qgis-ltr-bin.exe. Monkeypatchemos también
    os.__file__ para forzar el path de la estrategia 4 (sys.prefix)
    aislando los tests del os real del sistema.
    """
    fake_qgis_root = tmp_path / "Program Files" / "QGIS 3.34" / "bin"
    fake_qgis_root.mkdir(parents=True)
    fake_qgis_bin = fake_qgis_root / "qgis-ltr-bin.exe"
    fake_qgis_bin.write_bytes(b"")

    fake_python_root = tmp_path / "Program Files" / "QGIS 3.34" / "apps" / "Python312"
    fake_python_root.mkdir(parents=True)
    fake_python_exe = fake_python_root / "python.exe"
    fake_python_exe.write_bytes(b"")

    monkeypatch.setattr(ai.sys, "platform", "win32")
    monkeypatch.setattr(ai.sys, "executable", str(fake_qgis_bin))
    monkeypatch.setattr(ai.sys, "prefix", str(fake_python_root))
    # Forzar estrategia 4: simular os.__file__ apuntando a un lugar fake
    # donde NO existe python.exe arriba (así estrategia 3 falla y caemos
    # a sys.prefix).
    monkeypatch.setattr(ai.os, "__file__", str(tmp_path / "nowhere" / "Lib" / "os.py"))

    result = ai.qgis_python_executable()
    assert result == str(fake_python_exe)
    assert "qgis" not in os.path.basename(result).lower()


def test_qgis_python_executable_windows_uses_os_dunder_file(monkeypatch, tmp_path):
    """Estrategia 3 (la más robusta): derivar python.exe desde os.__file__.

    Funciona aún si sys.prefix está apuntando mal (caso QGIS-Windows con
    embebedor que setea sys.prefix al QGIS root en vez del Python root).
    """
    # Python root simulado: <tmp>/PythonReal con Lib/os.py y python.exe.
    python_root = tmp_path / "PythonReal"
    lib_dir = python_root / "Lib"
    lib_dir.mkdir(parents=True)
    fake_os_py = lib_dir / "os.py"
    fake_os_py.write_text("# fake os")
    fake_python_exe = python_root / "python.exe"
    fake_python_exe.write_bytes(b"")

    # Sys.prefix apunta a un directorio DISTINTO sin python.exe — la
    # estrategia 4 fallaría, pero la 3 (os.__file__) debe rescatarnos.
    wrong_prefix = tmp_path / "QgisRootWrong"
    wrong_prefix.mkdir()

    monkeypatch.setattr(ai.sys, "platform", "win32")
    monkeypatch.setattr(ai.sys, "executable", str(tmp_path / "qgis-bin.exe"))
    monkeypatch.setattr(ai.sys, "prefix", str(wrong_prefix))
    monkeypatch.setattr(ai.sys, "exec_prefix", str(wrong_prefix))
    monkeypatch.setattr(ai.sys, "base_prefix", str(wrong_prefix))
    monkeypatch.setattr(ai.os, "__file__", str(fake_os_py))

    assert ai.qgis_python_executable() == str(fake_python_exe)


def test_qgis_python_diagnostics_returns_keys():
    """Diagnóstico expone los campos que necesitamos en reportes de bug."""
    info = ai.qgis_python_diagnostics()
    for key in ("platform", "sys.executable", "sys.prefix", "resolved_python"):
        assert key in info, f"Falta key '{key}' en diagnostics"


# ── warm_up_geoai / is_geoai_warmed_up ────────────────────────────────────


def test_warm_up_initially_false():
    ai._reset_warm_up_for_tests()
    assert ai.is_geoai_warmed_up() is False


def test_warm_up_idempotent(monkeypatch):
    """Una vez calentado, llamadas subsiguientes son no-op rápidos."""
    ai._reset_warm_up_for_tests()
    call_count = {"n": 0}

    def fake_import(name):
        call_count["n"] += 1
        return types.ModuleType(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    # Pero warm_up_geoai usa `import geoai` literal, no importlib —
    # parchamos sys.modules para evitar el verdadero import.
    fake_geoai = types.ModuleType("geoai")
    monkeypatch.setitem(sys.modules, "geoai", fake_geoai)

    ai.warm_up_geoai()
    assert ai.is_geoai_warmed_up() is True

    ai.warm_up_geoai()  # segunda llamada → no-op
    ai.warm_up_geoai()  # tercera llamada → no-op
    # is_geoai_warmed_up sigue True, no se rompe nada.
    assert ai.is_geoai_warmed_up() is True


def test_warm_up_propagates_import_error(monkeypatch):
    """Si geoai no importa, warm_up_geoai propaga la excepción para
    que el caller la maneje."""
    ai._reset_warm_up_for_tests()

    # Asegurar que `import geoai` falle removiendo de sys.modules y
    # mockeando el meta_path para que no encuentre el módulo.
    if "geoai" in sys.modules:
        monkeypatch.delitem(sys.modules, "geoai", raising=False)

    class _BlockingFinder:
        def find_spec(self, name, path=None, target=None):
            if name == "geoai":
                return None
            return None

    monkeypatch.setattr(sys, "meta_path", [_BlockingFinder()])

    with pytest.raises(ImportError):
        ai.warm_up_geoai()

    # Y el flag NO debe quedar True si falló.
    assert ai.is_geoai_warmed_up() is False


def test_reset_warm_up_for_tests():
    """Helper de testing: re-setea el flag a False."""
    fake_geoai = types.ModuleType("geoai")
    sys.modules["geoai"] = fake_geoai
    try:
        ai.warm_up_geoai()
        assert ai.is_geoai_warmed_up() is True
        ai._reset_warm_up_for_tests()
        assert ai.is_geoai_warmed_up() is False
    finally:
        sys.modules.pop("geoai", None)
        ai._reset_warm_up_for_tests()


def test_qgis_python_executable_windows_real_python_passthrough(monkeypatch, tmp_path):
    """Si sys.executable YA es python.exe (Windows nativo, no QGIS),
    devolverlo tal cual sin tocar sys.prefix."""
    fake_python = tmp_path / "Python312" / "python.exe"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_bytes(b"")

    monkeypatch.setattr(ai.sys, "platform", "win32")
    monkeypatch.setattr(ai.sys, "executable", str(fake_python))

    assert ai.qgis_python_executable() == str(fake_python)


def test_qgis_python_executable_windows_python3_exe_fallback(monkeypatch, tmp_path):
    """Algunas distribuciones embeben python3.exe en vez de python.exe.

    Aislamos os.__file__ a un directorio sin python.exe para forzar la
    caída a estrategia 4 (sys.prefix).
    """
    fake_qgis_bin = tmp_path / "qgis-bin.exe"
    fake_qgis_bin.write_bytes(b"")
    fake_python_root = tmp_path / "apps" / "Python311"
    fake_python_root.mkdir(parents=True)
    fake_python3 = fake_python_root / "python3.exe"
    fake_python3.write_bytes(b"")

    monkeypatch.setattr(ai.sys, "platform", "win32")
    monkeypatch.setattr(ai.sys, "executable", str(fake_qgis_bin))
    monkeypatch.setattr(ai.sys, "prefix", str(fake_python_root))
    monkeypatch.setattr(ai.os, "__file__", str(tmp_path / "nowhere" / "Lib" / "os.py"))

    assert ai.qgis_python_executable() == str(fake_python3)


def test_qgis_python_executable_linux_returns_sys_executable_directly(monkeypatch):
    """En Linux/macOS sys.executable siempre es python correcto — no
    debe entrar a la lógica Windows-only de sys.prefix."""
    monkeypatch.setattr(ai.sys, "platform", "linux")
    monkeypatch.setattr(ai.sys, "executable", "/usr/bin/python3")
    assert ai.qgis_python_executable() == "/usr/bin/python3"


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
