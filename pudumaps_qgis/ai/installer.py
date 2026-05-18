"""Instalación de dependencias de IA contra el Python embebido de QGIS.

Patrón estándar QGIS para plugins que necesitan paquetes pesados:
ejecutar `python -m pip install --user` con el `sys.executable` del
proceso QGIS para que el paquete quede visible al `import` desde aquí.

NUNCA usar `python` del PATH — apunta al Python del sistema, no al de
QGIS, y la instalación quedaría invisible al plugin.

NUNCA correr sin `--user` salvo en venv dedicado: instalar en
site-packages global puede romper la instalación de QGIS al chocar con
GDAL/rasterio que QGIS ya provee.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional

from . import qgis_python_executable

# Callback invocado por cada línea de stdout/stderr del proceso pip.
# El UI lo usa para actualizar una QProgressDialog con texto.
ProgressCallback = Callable[[str], None]


@dataclass
class InstallResult:
    """Resultado de una instalación de paquete vía pip."""

    package: str
    version: Optional[str]
    success: bool
    exit_code: int
    output: str  # stdout + stderr combinados, para logging/debug
    error_message: Optional[str] = None


class InstallError(Exception):
    """Falla recuperable durante la instalación.

    El instalador no lanza esto desde `install_package` — devuelve un
    `InstallResult(success=False)`. Esta excepción existe para el caso
    en que el caller quiera convertirla con `result.raise_for_status()`.
    """


def _pip_command(package: str, version: Optional[str], extras: Optional[str]) -> List[str]:
    """Construye el comando pip pineando versión si se provee.

    Ejemplos:
        _pip_command("geoai-py", "0.10.0", None)
            → [..., "geoai-py==0.10.0"]
        _pip_command("GeoAgent", "0.4.0", "ollama,geoai")
            → [..., "GeoAgent[ollama,geoai]==0.4.0"]
    """
    spec = package
    if extras:
        spec = f"{spec}[{extras}]"
    if version:
        spec = f"{spec}=={version}"
    return [
        qgis_python_executable(),
        "-m",
        "pip",
        "install",
        "--user",
        "--disable-pip-version-check",
        "--no-input",
        spec,
    ]


def install_package(
    package: str,
    version: Optional[str] = None,
    extras: Optional[str] = None,
    progress_cb: Optional[ProgressCallback] = None,
    timeout_s: int = 1800,
) -> InstallResult:
    """Instala un paquete pip contra el Python de QGIS.

    Captura stdout línea a línea y la pasa por `progress_cb` para que el
    UI muestre progreso real. Combina stdout y stderr en `result.output`
    para logging completo.

    Args:
        package: nombre PyPI (ej. "geoai-py").
        version: versión exacta a pinear (ej. "0.10.0"). None = última.
        extras: extras entre corchetes (ej. "ollama,geoai"). Sin []s.
        progress_cb: callback `(line) -> None` por cada línea de salida.
        timeout_s: tope duro (default 30 min, suficiente para PyTorch).

    Returns:
        InstallResult con success, exit_code y output combinados.
    """
    cmd = _pip_command(package, version, extras)
    output_lines: List[str] = []

    try:
        process = subprocess.Popen(  # noqa: S603 (cmd construido localmente)
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as e:
        return InstallResult(
            package=package,
            version=version,
            success=False,
            exit_code=-1,
            output="",
            error_message=f"No se pudo lanzar pip: {e}",
        )

    assert process.stdout is not None
    try:
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            output_lines.append(line)
            if progress_cb is not None:
                try:
                    progress_cb(line)
                except Exception:  # noqa: BLE001
                    # Un callback roto no debe matar la instalación.
                    pass
        exit_code = process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
        return InstallResult(
            package=package,
            version=version,
            success=False,
            exit_code=-2,
            output="\n".join(output_lines),
            error_message=f"Timeout tras {timeout_s}s. ¿Conexión lenta?",
        )

    output = "\n".join(output_lines)
    if exit_code == 0:
        return InstallResult(
            package=package,
            version=version,
            success=True,
            exit_code=0,
            output=output,
        )

    return InstallResult(
        package=package,
        version=version,
        success=False,
        exit_code=exit_code,
        output=output,
        error_message=_summarize_failure(output, exit_code),
    )


def _summarize_failure(output: str, exit_code: int) -> str:
    """Extrae una línea legible del log de pip para mostrar al usuario."""
    # Buscar la primera línea con "ERROR:" que es lo que pip usa.
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("ERROR:"):
            return stripped[: 200]
    return f"pip falló con código {exit_code}."


__all__ = [
    "InstallError",
    "InstallResult",
    "ProgressCallback",
    "install_package",
]
