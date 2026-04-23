"""Upload a QgsVectorLayer to a Pudumaps project (new or existing layer)."""

from __future__ import annotations

from qgis.core import QgsVectorLayer
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..api_client import Project, PudumapsClient, PudumapsError
from ..exporter import ExportError, format_size, layer_to_geojson
from ..project_loader import PROP_LAYER_ID, PROP_PROJECT_ID, PROP_PROJECT_NAME
from ..styles import apply_pudumaps_style
from ..ui_helpers import build_header, separator


class UploadLayerDialog(QDialog):
    def __init__(
        self,
        client: PudumapsClient,
        layer: QgsVectorLayer,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.client = client
        self.layer = layer
        self.projects: list[Project] = []

        # Detect whether this layer originated in Pudumaps (came from pull).
        self.existing_remote_id: str = layer.customProperty(PROP_LAYER_ID, "") or ""
        self.pre_selected_project_id: str = (
            layer.customProperty(PROP_PROJECT_ID, "") or ""
        )

        self.setWindowTitle("Pudumaps — Subir capa")
        self.setMinimumWidth(560)
        apply_pudumaps_style(self)

        # Form widgets
        self.project_combo = QComboBox()
        self.project_combo.setEnabled(False)  # until projects load
        self.new_project_btn = QPushButton("＋ Nuevo…")
        self.new_project_btn.setToolTip("Crear un proyecto nuevo")
        self.new_project_btn.clicked.connect(self._create_new_project)

        self.name_edit = QLineEdit(layer.name())

        # Info/summary
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("color: #888; font-size: 11px;")

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        # Buttons
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.upload_btn = self.buttons.button(QDialogButtonBox.Ok)
        self.upload_btn.setText(
            "Actualizar en Pudumaps" if self.existing_remote_id else "Subir a Pudumaps"
        )
        self.upload_btn.setEnabled(False)
        self.buttons.accepted.connect(self._upload)
        self.buttons.rejected.connect(self.reject)

        # Layout
        form = QFormLayout()
        form.addRow("Nombre de la capa:", self.name_edit)

        project_row = QHBoxLayout()
        project_row.addWidget(self.project_combo, 1)
        project_row.addWidget(self.new_project_btn)
        form.addRow("Proyecto destino:", project_row)

        header_subtitle = (
            "Actualiza en Pudumaps la capa ya enlazada."
            if self.existing_remote_id
            else "Sube esta capa a un proyecto existente o crea uno nuevo."
        )

        main = QVBoxLayout()
        main.addWidget(build_header("Subir capa", header_subtitle))
        main.addWidget(separator())
        main.addLayout(form)
        main.addWidget(self.summary_label)
        main.addStretch()
        main.addWidget(self.status_label)
        main.addWidget(self.buttons)
        self.setLayout(main)

        self._populate_summary()
        self._load_projects()

    # ── Setup ────────────────────────────────────────────────────────────

    def _populate_summary(self) -> None:
        count = self.layer.featureCount()
        crs = self.layer.crs().authid() or "desconocido"
        note = ""
        if crs != "EPSG:4326":
            note = f" · se reproyectará a EPSG:4326"
        summary = (
            f"{count:,} feature(s) · CRS {crs}{note}"
        )
        if self.existing_remote_id:
            summary += (
                f"\n⟲ Esta capa vino de Pudumaps — se actualizará en el "
                "proyecto original."
            )
        self.summary_label.setText(summary)

    def _load_projects(self) -> None:
        self._set_status("Cargando proyectos…", ok=None)
        try:
            projects = self.client.list_projects()
        except PudumapsError as e:
            self._set_status(f"Error: {e}", ok=False)
            return

        self.projects = projects
        self.project_combo.clear()
        for p in projects:
            self.project_combo.addItem(p.name, p.id)

        # Pre-select the original project if this layer came from Pudumaps
        if self.pre_selected_project_id:
            idx = self.project_combo.findData(self.pre_selected_project_id)
            if idx >= 0:
                self.project_combo.setCurrentIndex(idx)
                # For existing remote layers we always stay in "update in-place"
                # mode — user changing the project would mean creating a new
                # remote copy, which is confusing. Lock the combo.
                if self.existing_remote_id:
                    self.project_combo.setEnabled(False)
                    self.new_project_btn.setEnabled(False)
                else:
                    self.project_combo.setEnabled(True)
        else:
            self.project_combo.setEnabled(True)

        if projects:
            self.upload_btn.setEnabled(True)
            self._set_status(
                f"{len(projects)} proyecto(s) disponible(s).",
                ok=None,
            )
        else:
            self._set_status(
                "No tienes proyectos. Crea uno con el botón «Nuevo…».",
                ok=None,
            )

    def _create_new_project(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Pudumaps — Nuevo proyecto", "Nombre del proyecto:"
        )
        if not ok or not name.strip():
            return
        try:
            project = self.client.create_project(name.strip())
        except PudumapsError as e:
            self._set_status(f"No se pudo crear el proyecto: {e}", ok=False)
            return
        # Append to combo and select
        self.projects.append(project)
        self.project_combo.addItem(project.name, project.id)
        self.project_combo.setCurrentIndex(self.project_combo.count() - 1)
        self.upload_btn.setEnabled(True)
        self._set_status(f"✓ Proyecto «{project.name}» creado.", ok=True)

    # ── Upload ───────────────────────────────────────────────────────────

    def _upload(self) -> None:
        project_id = self.project_combo.currentData()
        if not project_id:
            self._set_status("Selecciona un proyecto destino.", ok=False)
            return
        name = self.name_edit.text().strip()
        if not name:
            self._set_status("El nombre de la capa es obligatorio.", ok=False)
            return

        self._set_status("Exportando capa…", ok=None)
        self.upload_btn.setEnabled(False)
        try:
            geojson, summary = layer_to_geojson(self.layer)
        except ExportError as e:
            self._set_status(f"Error: {e}", ok=False)
            self.upload_btn.setEnabled(True)
            return

        self._set_status(
            f"Subiendo {summary.feature_count:,} features ({format_size(summary.size_bytes)})…",
            ok=None,
        )

        try:
            if self.existing_remote_id:
                remote = self.client.update_layer(
                    self.existing_remote_id, name=name, geojson=geojson
                )
                self._set_status(
                    f"✓ Capa «{remote.name}» actualizada.", ok=True
                )
            else:
                remote = self.client.upload_layer(project_id, name, geojson)
                # Stamp the new remote id on the local layer so the next
                # upload becomes an update in-place (and Fase 4 sync can
                # detect it as "from Pudumaps").
                project_name = self.project_combo.currentText()
                self.layer.setCustomProperty(PROP_LAYER_ID, remote.id)
                self.layer.setCustomProperty(PROP_PROJECT_ID, project_id)
                self.layer.setCustomProperty(PROP_PROJECT_NAME, project_name)
                self._set_status(
                    f"✓ Capa «{remote.name}» creada en «{project_name}».",
                    ok=True,
                )
        except PudumapsError as e:
            msg = f"Error subiendo: {e}"
            if e.status == 401:
                msg += "\nKey inválida. Revisa Configuración."
            elif e.status == 413:
                msg += "\nLa capa es demasiado grande. Simplifica antes de subir."
            elif e.status == 429:
                msg += "\nRate limit excedido. Intenta de nuevo en unos segundos."
            self._set_status(msg, ok=False)
            self.upload_btn.setEnabled(True)
            return
        except Exception as e:  # noqa: BLE001
            self._set_status(f"Error inesperado: {e}", ok=False)
            self.upload_btn.setEnabled(True)
            return

        # Success — close after a short delay so the user sees the status
        QMessageBox.information(self, "Pudumaps", self.status_label.text())
        self.accept()

    # ── Status ───────────────────────────────────────────────────────────

    def _set_status(self, text: str, ok: bool | None) -> None:
        color = (
            "#22c55e" if ok is True else "#ef4444" if ok is False else "#888"
        )
        self.status_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        self.status_label.setText(text)
