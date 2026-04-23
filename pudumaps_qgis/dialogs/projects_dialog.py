"""Projects list dialog — lists all user projects and opens one in QGIS."""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..api_client import Project, PudumapsClient, PudumapsError
from ..project_loader import load_project


class ProjectsDialog(QDialog):
    def __init__(self, client: PudumapsClient, parent: QWidget | None = None):
        super().__init__(parent)
        self.client = client
        self.projects: list[Project] = []

        self.setWindowTitle("Pudumaps — Abrir proyecto")
        self.setMinimumSize(640, 420)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Nombre", "Descripción", "Creado"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.doubleClicked.connect(self._open_selected)

        self.refresh_btn = QPushButton("Actualizar")
        self.refresh_btn.clicked.connect(self._load)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setMinimum(0)

        self.buttons = QDialogButtonBox()
        self.open_btn = self.buttons.addButton(
            "Abrir proyecto", QDialogButtonBox.AcceptRole
        )
        self.open_btn.clicked.connect(self._open_selected)
        self.buttons.addButton(QDialogButtonBox.Close).clicked.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(self.table)
        row = QVBoxLayout()
        row.addWidget(self.refresh_btn)
        layout.addLayout(row)
        layout.addWidget(self.progress)
        layout.addWidget(self.status_label)
        layout.addWidget(self.buttons)
        self.setLayout(layout)

        self._load()

    # ── Data loading ─────────────────────────────────────────────────────

    def _load(self) -> None:
        self._set_status("Cargando proyectos…", ok=None)
        self.refresh_btn.setEnabled(False)
        try:
            projects = self.client.list_projects()
        except PudumapsError as e:
            self._set_status(f"Error: {e}", ok=False)
            self.refresh_btn.setEnabled(True)
            return
        finally:
            self.refresh_btn.setEnabled(True)

        self.projects = projects
        self.table.setRowCount(len(projects))
        for row, p in enumerate(projects):
            self.table.setItem(row, 0, QTableWidgetItem(p.name))
            self.table.setItem(row, 1, QTableWidgetItem(p.description or ""))
            self.table.setItem(
                row, 2, QTableWidgetItem(p.created_at[:10] if p.created_at else "")
            )
        if projects:
            self.table.selectRow(0)
            self._set_status(
                f"{len(projects)} proyecto(s) disponible(s). "
                "Doble clic o Abrir para cargar.",
                ok=None,
            )
        else:
            self._set_status("No tienes proyectos todavía.", ok=None)

    # ── Open ─────────────────────────────────────────────────────────────

    def _open_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.projects):
            QMessageBox.warning(self, "Pudumaps", "Selecciona un proyecto primero.")
            return
        project = self.projects[row]
        self._load_project_with_progress(project)

    def _load_project_with_progress(self, project: Project) -> None:
        try:
            layer_count = len(self.client.list_layers(project.id))
        except PudumapsError as e:
            self._set_status(f"Error listando capas: {e}", ok=False)
            return

        if layer_count == 0:
            ans = QMessageBox.question(
                self,
                "Pudumaps",
                f'El proyecto "{project.name}" no tiene capas todavía. '
                "¿Abrirlo igual (crea un grupo vacío)?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                return

        self.progress.setVisible(True)
        self.progress.setMaximum(max(1, layer_count))
        self.progress.setValue(0)
        self.buttons.setEnabled(False)
        self.refresh_btn.setEnabled(False)

        def cb(done: int, total: int, current: str) -> None:
            self.progress.setMaximum(max(1, total))
            self.progress.setValue(done)
            if current:
                self._set_status(f"Cargando «{current}»… ({done}/{total})", ok=None)
            from qgis.PyQt.QtWidgets import QApplication

            QApplication.processEvents()

        try:
            result = load_project(self.client, project.id, project.name, progress_cb=cb)
        except PudumapsError as e:
            self._set_status(f"Error: {e}", ok=False)
            self.progress.setVisible(False)
            self.buttons.setEnabled(True)
            self.refresh_btn.setEnabled(True)
            return
        except Exception as e:  # noqa: BLE001
            self._set_status(f"Error inesperado: {e}", ok=False)
            self.progress.setVisible(False)
            self.buttons.setEnabled(True)
            self.refresh_btn.setEnabled(True)
            return

        self.progress.setVisible(False)
        self.buttons.setEnabled(True)
        self.refresh_btn.setEnabled(True)

        msg = f"✓ Cargadas {result.loaded} capa(s) en el grupo «{result.group_name}»."
        if result.failed:
            failed_lines = "\n".join(f"  · {n}: {err}" for n, err in result.failed)
            msg += f"\n\n{len(result.failed)} capa(s) fallaron:\n{failed_lines}"
            self._set_status(msg, ok=False)
        else:
            self._set_status(msg, ok=True)
            # Auto-close after a successful load
            self.accept()

    # ── Status helper ────────────────────────────────────────────────────

    def _set_status(self, text: str, ok: bool | None) -> None:
        color = (
            "#22c55e" if ok is True else "#ef4444" if ok is False else "#888"
        )
        self.status_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        self.status_label.setText(text)
