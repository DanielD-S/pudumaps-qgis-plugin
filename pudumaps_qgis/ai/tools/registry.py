"""Registro de acciones IA disponibles en el plugin.

Mantener la lista aquí — no via descubrimiento dinámico — para que
sea fácil ver de un vistazo qué expone el plugin y para evitar tener
que importar paquetes pesados (torch via geoai) al startup.

Para sumar una nueva tool:
    1. Crear `pudumaps_qgis/ai/tools/<nombre>.py` con una subclase
       de AITool.
    2. Agregar `<NombreTool>` a `_TOOL_CLASSES` debajo.
    3. Agregar un test en `tests/test_ai_registry.py` que verifique
       que la nueva id sea única y la clase implemente el contrato.
"""

from __future__ import annotations

from typing import List, Optional, Type

from .base import AITool
from .extract_buildings import ExtractBuildingsTool
from .extract_water import ExtractWaterTool

# Orden visible en el panel (top → bottom).
_TOOL_CLASSES: List[Type[AITool]] = [
    ExtractBuildingsTool,
    ExtractWaterTool,
]


def get_tools() -> List[AITool]:
    """Devuelve una instancia de cada tool registrada.

    Las tools son baratas de instanciar (no cargan geoai), así que
    crear una nueva lista en cada llamada es OK.
    """
    return [cls() for cls in _TOOL_CLASSES]


def get_tool(tool_id: str) -> Optional[AITool]:
    """Busca una tool por id. Devuelve None si no existe."""
    for cls in _TOOL_CLASSES:
        if cls.id == tool_id:
            return cls()
    return None


def tool_ids() -> List[str]:
    """Lista de ids registradas. Útil para validar uniqueness en tests."""
    return [cls.id for cls in _TOOL_CLASSES]


__all__ = ["get_tools", "get_tool", "tool_ids"]
