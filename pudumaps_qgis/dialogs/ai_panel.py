"""Panel lateral con las acciones IA del plugin.

QDockWidget que se acopla a la derecha del canvas QGIS. Muestra un
botón por cada tool registrada en `ai.tools.registry.get_tools()`. Si
las dependencias (`geoai`) no están instaladas, los botones se grisan
y un mensaje invita a abrir el instalador.

Las acciones se ejecutan en un `QgsTask` para no congelar la UI; el
resultado se carga automáticamente como capa vectorial al terminar.
"""

from __future__ import annotations

import os
import tempfile
from typing import Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..ai import is_geoai_available
from ..ai.tools import AITool, get_tools
from ..error_utils import log_full_error, safe_error_message
from ..styles import apply_pudumaps_style
from ..ui_helpers import build_header, separator, toast_error, toast_success


class AIToolsDock(QDockWidget):
    """Dock con las acciones IA disponibles."""

    OBJECT_NAME = "PudumapsAIToolsDock"

    def __init__(self, iface, parent=None):
        super().__init__("Pudumaps · IA", parent)
        self.setObjectName(self.OBJECT_NAME)
        self.iface = iface
        self._tools = get_tools()

        container = QWidget()
        apply_pudumaps_style(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        layout.addWidget(
            build_header(
                "Análisis IA",
                "Detección automática sobre tus capas — todo local.",
                logo_height=36,
            )
        )
        layout.addWidget(separator())

        self._availability_label = QLabel()
        self._availability_label.setWordWrap(True)
        self._availability_label.setStyleSheet("font-size: 11px; color: #666;")
        layout.addWidget(self._availability_label)

        self._buttons = []
        for tool in self._tools:
            btn = self._make_tool_button(tool)
            layout.addWidget(btn)
            self._buttons.append((tool, btn))

        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(container)
        scroll.setWidgetResizable(True)
        self.setWidget(scroll)

        self._refresh_availability()

    # ── Construcción de botones ─────────────────────────────────────

    def _make_tool_button(self, tool: AITool) -> QPushButton:
        btn = QPushButton(tool.name)
        btn.setToolTip(tool.description)
        btn.setMinimumHeight(36)
        btn.clicked.connect(lambda _checked=False, t=tool: self._run_tool(t))
        return btn

    def refresh(self) -> None:
        """Re-evalúa disponibilidad. Llamar tras instalar deps IA."""
        self._refresh_availability()

    def _refresh_availability(self) -> None:
        has_geoai = is_geoai_available()
        if has_geoai:
            self._availability_label.setText(
                "✓ Módulo IA detectado. Selecciona una capa y elige una acción."
            )
            self._availability_label.setStyleSheet(
                "font-size: 11px; color: #22c55e;"
            )
        else:
            self._availability_label.setText(
                "Módulo IA no instalado. Abre Pudumaps → Instalar módulo IA…"
            )
            self._availability_label.setStyleSheet(
                "font-size: 11px; color: #ef4444;"
            )

        for tool, btn in self._buttons:
            available = tool.is_available()
            btn.setEnabled(available)
            if not available:
                missing = ", ".join(tool.missing_requirements())
                btn.setToolTip(
                    f"{tool.description}\n\nFalta instalar: {missing}"
                )
            else:
                btn.setToolTip(tool.description)

    # ── Ejecución de tools ──────────────────────────────────────────

    def _run_tool(self, tool: AITool) -> None:
        """Valida input, prepara output path y dispara la tool en QgsTask.

        Async: la inferencia corre en thread background del task manager
        de QGIS. La UI no se congela y aparece una entry en el panel
        "Tasks" de QGIS con progreso y opción de cancelar.
        """
        layer = self.iface.activeLayer() if self.iface else None
        err = tool.validate_input(layer)
        if err:
            QMessageBox.warning(self, "Pudumaps · IA", err)
            return

        raster_path = _layer_source_path(layer)
        if not raster_path:
            QMessageBox.warning(
                self,
                "Pudumaps · IA",
                "No se pudo determinar el path en disco del raster.",
            )
            return

        output_path = _temp_output_path(tool.id, suffix=tool.output_suffix)

        # Import lazy: QgsApplication y AIToolTask solo cuando hace falta.
        from qgis.core import QgsApplication

        from ..ai.task_runner import AIToolTask

        layer_name = f"IA: {tool.name}"

        def on_success(out_path: str) -> None:
            _load_result_as_layer(self.iface, out_path, layer_name=layer_name)
            toast_success(self.iface, f"{tool.name} completado.")

        def on_error(msg: str) -> None:
            log_full_error(f"ai_panel.{tool.id}", RuntimeError(msg))
            toast_error(self.iface, safe_error_message(msg))

        task = AIToolTask(
            tool=tool,
            raster_path=raster_path,
            output_path=output_path,
            on_success=on_success,
            on_error=on_error,
            on_progress=lambda m: self._log(m),
        )
        # Aviso al usuario que la tarea está en cola.
        toast_success(
            self.iface,
            f"{tool.name} en ejecución — verás el progreso en el panel Tasks.",
        )
        QgsApplication.taskManager().addTask(task)
        # Mantener referencia para que el GC no lo recoja antes de que
        # QGIS lo termine. addTask transfiere ownership pero algunas
        # combinaciones de PyQt/sip se confunden si pierdes la ref.
        self._last_task = task

    def _log(self, msg: str) -> None:
        """Hook reservado para mostrar progreso. Por ahora a console."""
        try:
            from qgis.core import Qgis, QgsMessageLog

            QgsMessageLog.logMessage(msg, "Pudumaps · IA", level=Qgis.Info)
        except Exception:  # noqa: BLE001
            pass


# ── Helpers ─────────────────────────────────────────────────────────────


def _layer_source_path(layer) -> Optional[str]:
    """Devuelve el path en disco del raster, o None si no se puede."""
    if layer is None:
        return None
    source = getattr(layer, "source", None)
    if not callable(source):
        return None
    path = source()
    if not path:
        return None
    # QGIS a veces agrega query params al source — quedarnos con el path real.
    if "|" in path:
        path = path.split("|", 1)[0]
    return path if os.path.exists(path) else None


def _temp_output_path(tool_id: str, suffix: str = ".geojson") -> str:
    """Genera un path temporal único bajo el tempdir del SO."""
    fd, path = tempfile.mkstemp(prefix=f"pudumaps-ai-{tool_id}-", suffix=suffix)
    os.close(fd)
    return path


_RASTER_EXTS = {".tif", ".tiff", ".vrt", ".img"}
_VECTOR_EXTS = {".geojson", ".gpkg", ".shp", ".kml", ".json"}


def _load_result_as_layer(iface, path: str, layer_name: str) -> None:
    """Carga el resultado como capa en el proyecto QGIS.

    Despacha por extensión: GeoTIFF/VRT → `QgsRasterLayer`, GeoJSON/GPKG/
    SHP → `QgsVectorLayer`. Extensiones desconocidas se intentan como
    vector primero (cubre el caso más común).
    """
    if iface is None:
        return
    ext = os.path.splitext(path)[1].lower()
    try:
        from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer

        if ext in _RASTER_EXTS:
            layer = QgsRasterLayer(path, layer_name)
        else:
            # _VECTOR_EXTS y fallback genérico.
            layer = QgsVectorLayer(path, layer_name, "ogr")

        if not layer.isValid():
            toast_error(iface, "El resultado no se pudo cargar como capa.")
            return
        QgsProject.instance().addMapLayer(layer)
    except Exception as e:  # noqa: BLE001
        log_full_error("ai_panel._load_result_as_layer", e)


__all__ = ["AIToolsDock"]
