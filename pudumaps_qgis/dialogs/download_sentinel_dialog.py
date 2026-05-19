"""Diálogo para configurar una descarga Sentinel-2.

Pregunta:
- Bbox: por defecto el extent actual del canvas QGIS, o coordenadas
  custom en EPSG:4326.
- Rango de fechas: por defecto últimos 30 días.
- Cloud cover máximo: por defecto 20% (Chile central con cielos
  claros suele tener escenas <10% en verano; lluvioso patagónico
  puede requerir subir a 40-60%).

Devuelve `{"bbox": (xmin, ymin, xmax, ymax), "date_start": "YYYY-MM-DD",
"date_end": "YYYY-MM-DD", "cloud_max": int}` o None si canceló.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Optional, Tuple

from qgis.PyQt.QtCore import QDate, Qt
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from ..styles import apply_pudumaps_style
from ..ui_helpers import build_header, separator


def _canvas_bbox_4326(iface) -> Optional[Tuple[float, float, float, float]]:
    """Lee el extent del canvas reproyectado a EPSG:4326.

    None si iface o crs no están disponibles.
    """
    if iface is None:
        return None
    try:
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsCoordinateTransform,
            QgsProject,
        )
    except ImportError:
        return None

    try:
        canvas = iface.mapCanvas()
        extent = canvas.extent()
        canvas_crs = canvas.mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        if canvas_crs.authid() != "EPSG:4326":
            tr = QgsCoordinateTransform(canvas_crs, wgs84, QgsProject.instance())
            extent = tr.transformBoundingBox(extent)
        return (
            extent.xMinimum(),
            extent.yMinimum(),
            extent.xMaximum(),
            extent.yMaximum(),
        )
    except Exception:  # noqa: BLE001
        return None


class DownloadSentinelDialog(QDialog):
    """Modal de configuración de descarga Sentinel-2."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pudumaps · IA — Descargar Sentinel-2")
        self.setMinimumWidth(560)
        apply_pudumaps_style(self)

        self._iface = iface
        self._canvas_bbox = _canvas_bbox_4326(iface)
        self._result: Optional[Dict] = None

        intro = QLabel(
            "Descarga una composición RGB Sentinel-2 sobre el área indicada. "
            "El resultado se carga como capa raster en el proyecto y queda "
            "disponible para correr otras acciones IA encima."
        )
        intro.setWordWrap(True)

        # ── BBOX ─────────────────────────────────────────────────
        self.rb_canvas = QRadioButton("Usar extent actual del canvas")
        self.rb_custom = QRadioButton("Coordenadas custom (EPSG:4326)")
        self.bbox_group = QButtonGroup(self)
        self.bbox_group.addButton(self.rb_canvas)
        self.bbox_group.addButton(self.rb_custom)

        if self._canvas_bbox is not None:
            self.rb_canvas.setChecked(True)
            self.rb_canvas.setText(
                f"Usar extent del canvas: "
                f"({self._canvas_bbox[0]:.4f}, {self._canvas_bbox[1]:.4f}) → "
                f"({self._canvas_bbox[2]:.4f}, {self._canvas_bbox[3]:.4f})"
            )
        else:
            self.rb_canvas.setEnabled(False)
            self.rb_canvas.setText("Usar extent del canvas (no disponible)")
            self.rb_custom.setChecked(True)

        self.sb_xmin = self._make_coord_spin(-180, 180, -70.7)
        self.sb_ymin = self._make_coord_spin(-90, 90, -33.5)
        self.sb_xmax = self._make_coord_spin(-180, 180, -70.6)
        self.sb_ymax = self._make_coord_spin(-90, 90, -33.4)

        custom_row = QHBoxLayout()
        custom_row.addWidget(QLabel("xmin:"))
        custom_row.addWidget(self.sb_xmin)
        custom_row.addWidget(QLabel("ymin:"))
        custom_row.addWidget(self.sb_ymin)
        custom_row.addWidget(QLabel("xmax:"))
        custom_row.addWidget(self.sb_xmax)
        custom_row.addWidget(QLabel("ymax:"))
        custom_row.addWidget(self.sb_ymax)

        # ── Fechas ───────────────────────────────────────────────
        today = QDate.currentDate()
        thirty_days_ago = today.addDays(-30)
        self.dt_start = QDateEdit(thirty_days_ago)
        self.dt_end = QDateEdit(today)
        for w in (self.dt_start, self.dt_end):
            w.setDisplayFormat("yyyy-MM-dd")
            w.setCalendarPopup(True)
            w.setMaximumDate(today)

        # ── Cloud cover ──────────────────────────────────────────
        self.sb_cloud = QSpinBox()
        self.sb_cloud.setRange(0, 100)
        self.sb_cloud.setValue(20)
        self.sb_cloud.setSuffix("%")

        # ── Layout ───────────────────────────────────────────────
        form = QFormLayout()
        form.addRow("Área:", self.rb_canvas)
        form.addRow("", self.rb_custom)
        form.addRow("", _wrap(custom_row))
        form.addRow("Desde:", self.dt_start)
        form.addRow("Hasta:", self.dt_end)
        form.addRow("Nubosidad máxima:", self.sb_cloud)

        hint = QLabel(
            "Para Chile central conviene cloud_max ≤ 20%. En Patagonia o "
            "invierno puede ser necesario subir a 40-60% para que aparezcan "
            "escenas. El rango Sentinel-2 inicia el 2015-06-23."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 11px;")

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.buttons.button(QDialogButtonBox.Ok).setText("Descargar")
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(
            build_header(
                "Descargar Sentinel-2",
                "Composición RGB del área y rango indicados.",
            )
        )
        layout.addWidget(separator())
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addStretch()
        layout.addWidget(self.buttons)
        self.setLayout(layout)

    def _make_coord_spin(self, lo: float, hi: float, default: float) -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(lo, hi)
        sb.setDecimals(6)
        sb.setSingleStep(0.01)
        sb.setValue(default)
        return sb

    # ── Logic ────────────────────────────────────────────────────────

    def _on_accept(self) -> None:
        if self.rb_canvas.isChecked() and self._canvas_bbox is not None:
            bbox = self._canvas_bbox
        else:
            bbox = (
                float(self.sb_xmin.value()),
                float(self.sb_ymin.value()),
                float(self.sb_xmax.value()),
                float(self.sb_ymax.value()),
            )

        if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            QMessageBox.warning(
                self,
                "Pudumaps · IA",
                "El bbox es inválido: xmin debe ser < xmax e ymin < ymax.",
            )
            return

        d_start = self.dt_start.date()
        d_end = self.dt_end.date()
        if d_start > d_end:
            QMessageBox.warning(
                self,
                "Pudumaps · IA",
                "La fecha 'Desde' debe ser anterior o igual a 'Hasta'.",
            )
            return

        self._result = {
            "bbox": bbox,
            "date_start": d_start.toString("yyyy-MM-dd"),
            "date_end": d_end.toString("yyyy-MM-dd"),
            "cloud_max": int(self.sb_cloud.value()),
        }
        self.accept()

    def result_params(self) -> Optional[Dict]:
        return self._result


def _wrap(layout) -> "QWidget":  # type: ignore[name-defined]
    """Envuelve un layout en un QWidget para usarlo en QFormLayout.addRow."""
    from qgis.PyQt.QtWidgets import QWidget

    w = QWidget()
    w.setLayout(layout)
    return w


__all__ = ["DownloadSentinelDialog"]
