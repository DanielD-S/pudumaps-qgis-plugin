"""Diálogo para elegir los dos rásters de change detection.

Se invoca desde `ChangeDetectionTool.prompt_params()`. Lista los rásters
disponibles en el proyecto QGIS y deja al usuario elegir el "antes" y
el "después".

Devuelve un dict `{"raster_before": path, "raster_after": path}` al
aceptar, o None si el usuario cancela.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)

from ..styles import apply_pudumaps_style
from ..ui_helpers import build_header, separator


def _project_rasters(iface) -> List[Tuple[str, str]]:
    """Lista (nombre_display, path_en_disco) de los rásters del proyecto.

    Filtra capas sin path en disco (memory layers, vectoriales, etc.).
    """
    if iface is None:
        return []
    try:
        from qgis.core import QgsMapLayer, QgsProject
    except ImportError:
        return []

    out: List[Tuple[str, str]] = []
    for layer in QgsProject.instance().mapLayers().values():
        try:
            if layer.type() != QgsMapLayer.RasterLayer:
                continue
        except Exception:  # noqa: BLE001
            continue
        source = layer.source() if hasattr(layer, "source") else ""
        if not source:
            continue
        # Normalizar paths con query params estilo OGR.
        path = source.split("|", 1)[0]
        out.append((layer.name(), path))
    return out


class ChangeDetectionDialog(QDialog):
    """Modal con dos QComboBox de rásters."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pudumaps · IA — Detección de cambios")
        self.setMinimumWidth(540)
        apply_pudumaps_style(self)

        self._iface = iface
        self._rasters = _project_rasters(iface)
        self._result: Optional[Dict[str, str]] = None

        intro = QLabel(
            "Selecciona dos rásters del mismo bbox y distinta fecha. "
            "La tool produce una máscara binaria donde 1 = cambio "
            "detectado, 0 = sin cambio."
        )
        intro.setWordWrap(True)

        self.cb_before = QComboBox()
        self.cb_after = QComboBox()
        for name, path in self._rasters:
            self.cb_before.addItem(name, userData=path)
            self.cb_after.addItem(name, userData=path)

        # Si hay al menos 2 rásters, pre-seleccionar el segundo como "after".
        if len(self._rasters) >= 2:
            self.cb_after.setCurrentIndex(1)

        empty_warn = QLabel()
        empty_warn.setWordWrap(True)
        if not self._rasters:
            empty_warn.setText(
                "<b>No hay rásters en el proyecto.</b> Carga primero dos "
                "rásters (drag&drop o Capa → Añadir capa raster) y vuelve a abrir esta acción."
            )
            empty_warn.setStyleSheet("color: #ef4444;")
        elif len(self._rasters) == 1:
            empty_warn.setText(
                "<b>Solo hay 1 raster en el proyecto.</b> Carga el segundo "
                "(misma zona, distinta fecha) antes de ejecutar."
            )
            empty_warn.setStyleSheet("color: #ef4444;")

        form = QFormLayout()
        form.addRow("Raster antes:", self.cb_before)
        form.addRow("Raster después:", self.cb_after)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.buttons.button(QDialogButtonBox.Ok).setText("Ejecutar")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(len(self._rasters) >= 2)
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(
            build_header(
                "Detección de cambios",
                "Compara dos rásters y produce máscara binaria de cambio.",
            )
        )
        layout.addWidget(separator())
        layout.addWidget(intro)
        layout.addLayout(form)
        if empty_warn.text():
            layout.addWidget(empty_warn)
        layout.addStretch()
        layout.addWidget(self.buttons)
        self.setLayout(layout)

    def _on_accept(self) -> None:
        before = self.cb_before.currentData()
        after = self.cb_after.currentData()
        if not before or not after:
            QMessageBox.warning(self, "Pudumaps · IA", "Selecciona ambos rásters.")
            return
        if before == after:
            QMessageBox.warning(
                self,
                "Pudumaps · IA",
                "Los dos rásters son el mismo. Selecciona uno distinto para 'después'.",
            )
            return
        self._result = {"raster_before": before, "raster_after": after}
        self.accept()

    def result_params(self) -> Optional[Dict[str, str]]:
        """None si canceló, dict con paths si confirmó."""
        return self._result


__all__ = ["ChangeDetectionDialog"]
