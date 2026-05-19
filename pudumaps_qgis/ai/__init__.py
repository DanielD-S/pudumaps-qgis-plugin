"""Módulo de IA del plugin Pudumaps.

Contiene la integración opcional con `geoai-py` (visión por computadora
geoespacial) y `GeoAgent` (asistente conversacional). Ambas son
dependencias opcionales que el usuario instala desde el plugin mismo
contra el Python embebido de QGIS (no contra el Python del sistema).

Versiones pineadas: el plugin solo se asegura contra estas versiones
exactas. Bumps son manuales y controlados en cada release del plugin.
Esto protege contra rupturas por versiones rotas o yankeadas upstream.

Ver `docs/contingency-fork.md` para el plan B si las deps upstream
desaparecen.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from typing import Optional

# Versiones exactas requeridas. Bump manual por release del plugin.
GEOAI_PINNED_VERSION = "0.10.0"
GEOAGENT_PINNED_VERSION = "0.4.0"

# PyPI package names (pueden diferir del nombre de import).
GEOAI_PACKAGE = "geoai-py"
GEOAGENT_PACKAGE = "GeoAgent"

# Import names (lo que se hace `import X` en Python).
GEOAI_IMPORT = "geoai"
GEOAGENT_IMPORT = "geoagent"


def _module_version(module_name: str) -> Optional[str]:
    """Devuelve la versión declarada del módulo, o None si no se puede leer."""
    try:
        mod = importlib.import_module(module_name)
    except ImportError:
        return None
    version = getattr(mod, "__version__", None)
    if isinstance(version, str):
        return version
    return None


def is_geoai_available() -> bool:
    """True si `geoai` se puede importar en el Python de QGIS."""
    return importlib.util.find_spec(GEOAI_IMPORT) is not None


def is_geoagent_available() -> bool:
    """True si `geoagent` (paquete GeoAgent) se puede importar."""
    return importlib.util.find_spec(GEOAGENT_IMPORT) is not None


def geoai_version() -> Optional[str]:
    """Versión instalada de geoai, o None si no está disponible."""
    return _module_version(GEOAI_IMPORT)


def geoagent_version() -> Optional[str]:
    """Versión instalada de GeoAgent, o None si no está disponible."""
    return _module_version(GEOAGENT_IMPORT)


def geoai_matches_pin() -> bool:
    """True si la versión instalada coincide con la pineada."""
    return geoai_version() == GEOAI_PINNED_VERSION


def geoagent_matches_pin() -> bool:
    """True si la versión instalada coincide con la pineada."""
    return geoagent_version() == GEOAGENT_PINNED_VERSION


def qgis_python_executable() -> str:
    r"""Path al intérprete Python embebido de QGIS.

    Usar este path (NO `python` del PATH) para invocar pip y asegurar
    que las dependencias se instalan donde QGIS las verá.

    Gotcha Windows: en QGIS-Windows `sys.executable` apunta al **binario
    GUI de QGIS** (`qgis-bin.exe` / `qgis-ltr-bin.exe`), NO a python.exe.
    Si invocas `subprocess.run([sys.executable, "-m", "pip", ...])`,
    Windows relanza QGIS con esos argumentos en vez de pip — y QGIS
    interpreta "geoai-py==0.10.0" como un archivo de proyecto, fallando
    con "could not be found".

    `sys.prefix` sí apunta consistentemente al directorio de la
    instalación de Python (en QGIS-Windows: `…\apps\PythonXX\`). Desde
    ahí python.exe está garantizado.

    Linux/macOS: `sys.executable` ya es python correcto.
    """
    # Linux / macOS: sys.executable es python correcto.
    if sys.platform != "win32":
        return sys.executable

    # Windows: si sys.executable termina en python(.exe), usarlo.
    exe = sys.executable
    base = os.path.basename(exe).lower()
    if base.startswith("python") and base.endswith(".exe"):
        return exe

    # Caso QGIS-Windows: derivar python.exe desde sys.prefix.
    candidate = os.path.join(sys.prefix, "python.exe")
    if os.path.isfile(candidate):
        return candidate

    # Algunas distribuciones de QGIS embeben python3.exe en vez de python.exe.
    candidate3 = os.path.join(sys.prefix, "python3.exe")
    if os.path.isfile(candidate3):
        return candidate3

    # Último intento: buscar en sys.prefix/Scripts/ o sys.prefix/bin/.
    for subdir in ("Scripts", "bin"):
        candidate = os.path.join(sys.prefix, subdir, "python.exe")
        if os.path.isfile(candidate):
            return candidate

    # Fallback al sys.executable original — fallará pero al menos no
    # silenciamos el error.
    return exe


__all__ = [
    "GEOAI_PACKAGE",
    "GEOAGENT_PACKAGE",
    "GEOAI_IMPORT",
    "GEOAGENT_IMPORT",
    "GEOAI_PINNED_VERSION",
    "GEOAGENT_PINNED_VERSION",
    "is_geoai_available",
    "is_geoagent_available",
    "geoai_version",
    "geoagent_version",
    "geoai_matches_pin",
    "geoagent_matches_pin",
    "qgis_python_executable",
]
