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
    Windows relanza QGIS con esos argumentos — y QGIS interpreta
    "geoai-py==0.10.0" como archivo de proyecto.

    Estrategia (en orden de robustez):
      1) Linux/macOS: `sys.executable` ya es python correcto. Listo.
      2) Si `sys.executable` ya es python(.exe), usarlo.
      3) Derivar desde `os.__file__` — siempre apunta a `<python_root>/Lib/os.py`,
         así que `python_root` queda fijo independiente de cómo el embebedor
         de QGIS haya configurado `sys.prefix`. **Más robusto.**
      4) Probar `sys.prefix`, `sys.exec_prefix`, `sys.base_prefix` + nombres
         comunes (python.exe, python3.exe, pythonw.exe).
      5) Buscar `apps/Python*/python.exe` bajo esos prefijos (estructura
         típica OSGeo4W).
      6) Fallback final: `sys.executable` original. Falla, pero al menos
         no enmascara el problema.

    Devuelve siempre un string. El caller debería verificar que el path
    final existe antes de invocarlo.
    """
    if sys.platform != "win32":
        return sys.executable

    exe = sys.executable
    base = os.path.basename(exe).lower()
    if base.startswith("python") and base.endswith(".exe"):
        return exe

    candidate_names = ("python.exe", "python3.exe", "pythonw.exe")

    # Estrategia 3: derivar desde os.__file__ (siempre dentro de <python_root>/Lib/).
    # Esto es independiente de sys.prefix, que algunos embebedores
    # configuran apuntando al directorio de la app (QGIS root) en vez
    # del directorio de Python.
    try:
        os_module_path = os.__file__
    except AttributeError:
        os_module_path = None
    if os_module_path:
        # os.py vive en <python_root>/Lib/os.py → subir 2 niveles.
        try:
            python_root = os.path.dirname(os.path.dirname(os.path.abspath(os_module_path)))
            for name in candidate_names:
                candidate = os.path.join(python_root, name)
                if os.path.isfile(candidate):
                    return candidate
        except OSError:
            pass

    # Estrategia 4: probar todos los prefijos disponibles + nombres.
    prefixes = []
    for attr in ("prefix", "exec_prefix", "base_prefix", "base_exec_prefix"):
        value = getattr(sys, attr, None)
        if value and value not in prefixes:
            prefixes.append(value)

    for root in prefixes:
        for name in candidate_names:
            candidate = os.path.join(root, name)
            if os.path.isfile(candidate):
                return candidate
        # Subdirs típicos en algunas distribuciones.
        for subdir in ("Scripts", "bin"):
            for name in candidate_names:
                candidate = os.path.join(root, subdir, name)
                if os.path.isfile(candidate):
                    return candidate

    # Estrategia 5: buscar `apps/Python*/python.exe` (OSGeo4W layout).
    for root in prefixes:
        apps_dir = os.path.join(root, "apps")
        if not os.path.isdir(apps_dir):
            continue
        try:
            entries = os.listdir(apps_dir)
        except OSError:
            continue
        for entry in entries:
            if not entry.lower().startswith("python"):
                continue
            for name in candidate_names:
                candidate = os.path.join(apps_dir, entry, name)
                if os.path.isfile(candidate):
                    return candidate

    # Estrategia 6: rendirse y devolver lo que teníamos.
    return exe


def qgis_python_diagnostics() -> dict:
    """Snapshot de variables relevantes para diagnosticar bugs del instalador.

    El instalador la incluye en el log cuando falla, así reportes de
    bugs traen siempre el contexto que necesitamos (qué es sys.executable,
    qué prefijos vio, qué resolución obtuvo `qgis_python_executable`).

    No tiene side effects ni hace I/O — solo lee atributos de sys/os.
    """
    info = {
        "platform": sys.platform,
        "sys.executable": sys.executable,
        "sys.prefix": sys.prefix,
        "sys.exec_prefix": getattr(sys, "exec_prefix", None),
        "sys.base_prefix": getattr(sys, "base_prefix", None),
        "os.__file__": getattr(os, "__file__", None),
        "resolved_python": qgis_python_executable(),
    }
    return info


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
    "qgis_python_diagnostics",
]
