"""Tests del instalador pip --user contra el Python embebido de QGIS.

Mockean subprocess.Popen para no instalar paquetes reales en CI.
Verifican:
- el comando usa sys.executable (no 'python' del PATH)
- la versión se pinea con ==
- los extras se serializan como [extras]
- la captura línea a línea invoca progress_cb
- exit codes != 0 producen InstallResult.success=False con error_message
- timeouts se manejan sin hanging
"""

from __future__ import annotations

import io
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from pudumaps_qgis.ai import installer
from pudumaps_qgis.ai.installer import (
    InstallResult,
    _pip_command,
    _summarize_failure,
    install_package,
)


# ── Tests puros (sin subprocess) ─────────────────────────────────────────


def test_pip_command_uses_qgis_python():
    """El primer elemento del comando debe ser sys.executable."""
    cmd = _pip_command("geoai-py", "0.10.0", None)
    assert cmd[0] == sys.executable
    assert cmd[1:5] == ["-m", "pip", "install", "--user"]


def test_pip_command_pins_version():
    """La versión se pega al spec con '=='."""
    cmd = _pip_command("geoai-py", "0.10.0", None)
    assert "geoai-py==0.10.0" in cmd


def test_pip_command_without_version():
    """Sin versión, el spec va sin '=='."""
    cmd = _pip_command("geoai-py", None, None)
    assert "geoai-py" in cmd
    assert not any("==" in c for c in cmd)


def test_pip_command_with_extras():
    """Los extras van entre [] dentro del spec."""
    cmd = _pip_command("GeoAgent", "0.4.0", "ollama,geoai")
    assert "GeoAgent[ollama,geoai]==0.4.0" in cmd


def test_pip_command_includes_safety_flags():
    """--disable-pip-version-check y --no-input para no colgar."""
    cmd = _pip_command("geoai-py", "0.10.0", None)
    assert "--disable-pip-version-check" in cmd
    assert "--no-input" in cmd


def test_summarize_failure_extracts_error_line():
    """_summarize_failure prefiere la línea 'ERROR:' de pip."""
    output = (
        "Looking in indexes: https://pypi.org/simple\n"
        "Collecting geoai-py==0.10.0\n"
        "ERROR: No matching distribution found for geoai-py==0.10.0\n"
    )
    summary = _summarize_failure(output, 1)
    assert "No matching distribution" in summary


def test_summarize_failure_fallback_to_exit_code():
    """Si no hay 'ERROR:', devuelve mensaje con el exit code."""
    summary = _summarize_failure("blah\nblah\n", 99)
    assert "99" in summary


# ── Tests con subprocess mockeado ─────────────────────────────────────────


def _fake_popen(stdout_lines: list[str], exit_code: int = 0):
    """Construye un mock de subprocess.Popen que itera por stdout_lines."""
    proc = MagicMock()
    proc.stdout = iter(line + "\n" for line in stdout_lines)
    proc.wait.return_value = exit_code
    return proc


def test_install_package_success_collects_output_and_calls_progress():
    """Con exit_code=0, el resultado es success=True y progress_cb recibe líneas."""
    lines_seen: list[str] = []

    fake_lines = [
        "Collecting geoai-py==0.10.0",
        "Downloading geoai_py-0.10.0-py3-none-any.whl (1.2 MB)",
        "Successfully installed geoai-py-0.10.0",
    ]

    with patch.object(installer.subprocess, "Popen", return_value=_fake_popen(fake_lines, 0)):
        result = install_package(
            "geoai-py",
            version="0.10.0",
            progress_cb=lines_seen.append,
        )

    assert result.success is True
    assert result.exit_code == 0
    assert result.package == "geoai-py"
    assert result.version == "0.10.0"
    assert "Successfully installed" in result.output
    assert lines_seen == fake_lines


def test_install_package_failure_has_error_message():
    """Con exit_code != 0, success=False y error_message poblado."""
    fake_lines = [
        "Collecting geoai-py==99.99.99",
        "ERROR: No matching distribution found for geoai-py==99.99.99",
    ]
    with patch.object(installer.subprocess, "Popen", return_value=_fake_popen(fake_lines, 1)):
        result = install_package("geoai-py", version="99.99.99")

    assert result.success is False
    assert result.exit_code == 1
    assert result.error_message is not None
    assert "No matching distribution" in result.error_message


def test_install_package_handles_popen_oserror():
    """Si Popen lanza OSError (binario no encontrado), no rompe — devuelve fail."""
    with patch.object(
        installer.subprocess,
        "Popen",
        side_effect=OSError("python not found"),
    ):
        result = install_package("geoai-py", version="0.10.0")

    assert result.success is False
    assert result.exit_code == -1
    assert result.error_message is not None
    assert "python not found" in result.error_message


def test_install_package_broken_progress_cb_does_not_abort():
    """Si el progress_cb explota, la instalación sigue."""

    def crashing_cb(line: str) -> None:
        raise RuntimeError("UI crashed")

    fake_lines = ["A", "B", "Successfully installed geoai-py-0.10.0"]
    with patch.object(installer.subprocess, "Popen", return_value=_fake_popen(fake_lines, 0)):
        result = install_package(
            "geoai-py",
            version="0.10.0",
            progress_cb=crashing_cb,
        )

    assert result.success is True


def test_install_package_timeout_kills_process():
    """Si pip excede el timeout, se mata el proceso y se devuelve exit_code=-2."""
    proc = MagicMock()
    proc.stdout = iter(["line\n"])
    # Primer wait() (con timeout_s) lanza Timeout; el segundo wait() post-kill
    # debe completar limpio, así que usamos una secuencia de side_effects.
    proc.wait.side_effect = [
        subprocess.TimeoutExpired(cmd="pip", timeout=1),
        -9,  # kill exit code
    ]

    with patch.object(installer.subprocess, "Popen", return_value=proc):
        result = install_package("geoai-py", version="0.10.0", timeout_s=1)

    assert result.success is False
    assert result.exit_code == -2
    assert "Timeout" in (result.error_message or "")
    proc.kill.assert_called_once()
