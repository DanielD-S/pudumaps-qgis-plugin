"""Contrato base para acciones IA del plugin Pudumaps.

Toda nueva herramienta hereda de `AITool` y define:
- `id` único (slug usado en logs, registry, settings).
- `name` / `description` para mostrar en el panel.
- `requires`: lista de paquetes pip requeridos (ej. ["geoai"]).
- `validate_input(layer)`: error msg si la capa no sirve, None si OK.
- `run(raster_path, output_path, params, progress_cb)`: ejecuta la
  inferencia y deja el resultado en `output_path`. Devuelve el path.

Las subclases NO deben importar `geoai`/`torch` al tope del archivo:
import lazy dentro de `run()` para que cargar el módulo no traiga
PyTorch (~2 GB) al startup del plugin.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional

from .. import is_geoai_available, is_geoagent_available

ProgressCallback = Callable[[str], None]


class AIToolError(Exception):
    """Error recuperable durante la ejecución de una tool IA.

    Las subclases lanzan esto cuando un input es inválido, falta un
    archivo, geoai devuelve algo inesperado, etc. El panel atrapa esta
    excepción y muestra el mensaje al usuario.
    """


class AIToolUnavailable(AIToolError):
    """La tool no puede correr porque le faltan dependencias.

    Lo lanzamos al inicio de `run()` si el usuario invoca la acción sin
    tener los paquetes instalados. El panel debería evitar este caso
    deshabilitando el botón, pero esta defensa cubre la ruta directa.
    """


# Mapa de paquete-requirement → función que chequea disponibilidad. Si
# agregamos un nuevo provider (ej. samgeo, deepness), basta con sumar
# entrada acá.
_REQUIREMENT_CHECKS: Dict[str, Callable[[], bool]] = {
    "geoai": is_geoai_available,
    "geoagent": is_geoagent_available,
}


class AITool(ABC):
    """Acción IA del plugin."""

    # ── Subclases deben sobreescribir ───────────────────────────────

    id: str = ""
    name: str = ""
    description: str = ""
    requires: List[str] = []  # ["geoai"], ["geoai", "geoagent"], ...

    # Tipo de input esperado: "raster" o "vector".
    # El panel usa esto para auto-seleccionar la capa activa correcta.
    input_kind: str = "raster"

    # Sufijo del archivo de salida que esta tool produce. El panel usa
    # esto para crear el path temporal con la extensión correcta y para
    # decidir si carga el resultado como QgsVectorLayer o QgsRasterLayer.
    # Por defecto las tools de segmentación producen GeoJSON; las de
    # clasificación pixel-wise producen GeoTIFF.
    output_suffix: str = ".geojson"

    # ── API pública ─────────────────────────────────────────────────

    @classmethod
    def is_available(cls) -> bool:
        """True si todas las dependencias listadas en `requires` están
        instaladas. Usado por el panel para grisar botones."""
        return all(
            _REQUIREMENT_CHECKS.get(req, lambda: False)()
            for req in cls.requires
        )

    @classmethod
    def missing_requirements(cls) -> List[str]:
        """Lista de paquetes en `requires` que NO están disponibles.

        Útil para mostrar un mensaje claro al usuario:
        'Falta instalar: geoai, geoagent'.
        """
        return [
            req
            for req in cls.requires
            if not _REQUIREMENT_CHECKS.get(req, lambda: False)()
        ]

    # ── Subclases implementan ───────────────────────────────────────

    @abstractmethod
    def validate_input(self, layer) -> Optional[str]:
        """Verifica que la capa sea apta para esta tool.

        Returns:
            None si la capa sirve, o un string con el motivo del rechazo
            (ej. "Esta acción requiere una capa raster.").

        Mantener este método PURO (sin side effects, sin red, sin
        archivos) — el panel lo invoca en hot path para grisar botones.
        """

    @abstractmethod
    def run(
        self,
        raster_path: str,
        output_path: str,
        params: Optional[Dict] = None,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> str:
        """Ejecuta la inferencia y deja el resultado en `output_path`.

        Args:
            raster_path: path al archivo raster en disco (GeoTIFF, etc.).
            output_path: path destino para el resultado (típicamente
                GeoJSON para detección, GeoTIFF para máscaras).
            params: parámetros adicionales específicos de la tool.
            progress_cb: callback opcional `(msg) -> None` para actualizar
                la UI con mensajes de progreso.

        Returns:
            El `output_path` (mismo que entra, por conveniencia de chain).

        Raises:
            AIToolUnavailable: faltan dependencias.
            AIToolError: input inválido o fallo de inferencia.
        """

    # ── Helper común ────────────────────────────────────────────────

    def ensure_available(self) -> None:
        """Levanta AIToolUnavailable si faltan deps. Llamar al inicio de run()."""
        missing = self.missing_requirements()
        if missing:
            packages = ", ".join(missing)
            raise AIToolUnavailable(
                f"Faltan paquetes para '{self.name}': {packages}. "
                f"Abre Pudumaps → Instalar módulo IA…"
            )


__all__ = [
    "AITool",
    "AIToolError",
    "AIToolUnavailable",
    "ProgressCallback",
]
