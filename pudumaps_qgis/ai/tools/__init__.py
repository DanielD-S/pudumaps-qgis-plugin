"""Acciones IA del plugin Pudumaps.

Cada acción hereda de `AITool` (ver `base.py`) y queda registrada en
`registry.get_tools()`. El panel IA (`dialogs/ai_panel.py`) descubre
las acciones desde el registry, así que agregar una nueva tool no
requiere tocar UI.

Contrato:
- `run(raster_path, output_path, params, progress_cb) -> output_path`
- Las acciones que invocan geoai/torch lo hacen lazy (dentro de run)
  para no pagar el costo de importar PyTorch al cargar el plugin.
- Las acciones se ejecutan en `QgsTask` desde el panel para no
  congelar la UI de QGIS.
"""

from .base import AITool, AIToolError, AIToolUnavailable
from .registry import get_tool, get_tools

__all__ = [
    "AITool",
    "AIToolError",
    "AIToolUnavailable",
    "get_tool",
    "get_tools",
]
