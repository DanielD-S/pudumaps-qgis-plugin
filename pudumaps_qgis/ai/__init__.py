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
GEOAGENT_PINNED_VERSION = "1.8.0"

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


# ── Warm-up del main thread ─────────────────────────────────────────────
#
# PyTorch en Windows requiere que `import torch` ocurra desde el main
# thread del proceso — si lo hace un thread worker (caso QgsTask),
# falla con "DLL load failed while importing lib" porque el loader de
# DLLs de Windows no resuelve algunos paths desde threads non-main.
#
# Llamar `warm_up_geoai()` desde el main thread (típicamente desde el
# panel IA antes de lanzar el primer task) carga torch+geoai en
# `sys.modules`. Tasks subsiguientes hacen `import geoai` y obtienen
# el módulo cacheado sin re-inicializar DLLs.
#
# Variable a módulo (singleton). Se setea en True tras el primer
# import exitoso y persiste por la vida del proceso QGIS.

_warmed_up = False


def is_geoai_warmed_up() -> bool:
    """True si `warm_up_geoai()` ya cargó torch+geoai con éxito."""
    return _warmed_up


def warm_up_geoai_environment_only() -> None:
    """Prepara env vars / DLL paths SIN importar geoai. Útil para tests."""
    _prepare_torch_environment()


def warm_up_geoai() -> None:
    """Importa geoai (y toda su cadena: torch, transformers, etc.)
    desde el thread actual.

    BLOQUEANTE — toma 30-90 segundos la primera vez por sesión, mucho
    menos en llamadas subsiguientes (idempotente: solo hace work la
    primera vez).

    DEBE llamarse desde el main thread del proceso QGIS. Si se llama
    desde un thread worker, el `import torch` fallará con
    "DLL load failed" en Windows.

    Raises:
        ImportError si geoai no se puede cargar (deps faltantes, DLL
        rota, etc.). Lo dejamos propagar para que el caller pueda
        manejar el error con un mensaje al usuario.
    """
    global _warmed_up
    if _warmed_up:
        return
    # Preparar env vars / DLL directories ANTES del import. Esto
    # resuelve el conflicto MKL/OpenMP entre QGIS y PyTorch en Windows
    # (síntoma: "DLL load failed while importing lib").
    _prepare_torch_environment()
    # Importar geoai trae torch + transformers + segmentation_models + ...
    # Toda la cadena queda cacheada en sys.modules.
    import geoai  # noqa: F401
    _warmed_up = True


def _reset_warm_up_for_tests() -> None:
    """Resetea el flag — solo para tests."""
    global _warmed_up
    _warmed_up = False


def _prepare_torch_environment() -> None:
    """Ajusta env vars / DLL directories para que torch cargue en QGIS-Windows.

    QGIS bundles su propio Qt + Intel MKL + OpenMP runtime. PyTorch también
    trae estas libs. Cuando ambos se cargan en el mismo proceso, MKL aborta
    con un mensaje sobre "multiple copies of OpenMP runtime" o falla con
    "DLL load failed while importing lib" (mensaje genérico pero típicamente
    es el conflicto MKL).

    Estas dos variables son los workarounds estándar documentados por
    Intel/PyTorch:
    - KMP_DUPLICATE_LIB_OK=TRUE: permite múltiples copias de OpenMP en el
      proceso. Hay un riesgo teórico de resultados numéricos no idénticos
      entre runs, pero en práctica nadie ha reportado problemas reales.
    - os.add_dll_directory(torch/lib): registra el path de torch para que
      el loader de Windows encuentre sus DLLs aunque QGIS haya tocado PATH.

    Idempotente: llamar varias veces no hace daño.
    """
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

    # Registrar torch/lib/ como DLL directory si torch ya está instalado.
    # Hacemos best-effort: si falla, seguimos — el import después puede
    # funcionar de todas formas.
    try:
        # No importamos torch acá (eso es lo que estamos preparando).
        # Localizamos su carpeta `lib/` por sys.path / find_spec.
        import importlib.util as _ilu

        spec = _ilu.find_spec("torch")
        if spec is not None and spec.origin:
            torch_dir = os.path.dirname(spec.origin)
            torch_lib = os.path.join(torch_dir, "lib")
            if os.path.isdir(torch_lib) and hasattr(os, "add_dll_directory"):
                os.add_dll_directory(torch_lib)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        # Si find_spec rompe, simplemente seguimos sin pre-registrar. El
        # import principal va a fallar con mensaje claro si torch no está.
        pass


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
    "warm_up_geoai",
    "is_geoai_warmed_up",
]
