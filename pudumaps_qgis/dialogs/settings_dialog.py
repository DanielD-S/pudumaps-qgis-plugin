"""Pudumaps settings dialog.

Built programmatically instead of loading a .ui file to keep the plugin
simple and avoid the pyrcc5/pyuic5 build step for version 0.1.
"""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..api_client import DEFAULT_BASE_URL, PudumapsClient, PudumapsError
from ..auth import clear_credentials, load_credentials, save_credentials
from ..styles import apply_pudumaps_style
from ..ui_helpers import build_header, separator


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pudumaps — Configuración")
        self.setMinimumWidth(540)
        apply_pudumaps_style(self)

        # Form
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("pdmp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")

        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText(DEFAULT_BASE_URL)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.test_btn = QPushButton("Probar conexión")
        self.test_btn.clicked.connect(self._test_connection)

        self.clear_btn = QPushButton("Borrar credenciales")
        self.clear_btn.clicked.connect(self._clear)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        self.buttons.accepted.connect(self._save_and_close)
        self.buttons.rejected.connect(self.reject)

        # Layout
        form = QFormLayout()
        form.addRow("API Key:", self.api_key_edit)
        form.addRow("Base URL:", self.base_url_edit)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.test_btn)
        btn_row.addWidget(self.clear_btn)
        btn_row.addStretch()

        hint = QLabel(
            "Obtén tu API key desde el Dashboard de Pudumaps:\n"
            "Configuración → API → Nueva key.\n"
            "Requiere plan Pro o superior."
        )
        hint.setStyleSheet("color: #888; font-size: 11px;")
        hint.setWordWrap(True)

        main = QVBoxLayout()
        main.addWidget(
            build_header(
                "Configuración",
                "Conecta tu cuenta Pudumaps para pull, push y sync de proyectos.",
            )
        )
        main.addWidget(separator())
        main.addLayout(form)
        main.addLayout(btn_row)
        main.addWidget(self.status_label)
        main.addStretch()
        main.addWidget(hint)
        main.addWidget(self.buttons)
        self.setLayout(main)

        self._load_existing()

    # ── Logic ────────────────────────────────────────────────────────────

    def _load_existing(self) -> None:
        creds = load_credentials()
        if creds:
            self.api_key_edit.setText(creds.api_key)
            self.base_url_edit.setText(creds.base_url)
        else:
            self.base_url_edit.setText(DEFAULT_BASE_URL)

    def _current_creds(self) -> tuple[str, str]:
        api_key = self.api_key_edit.text().strip()
        base_url = self.base_url_edit.text().strip() or DEFAULT_BASE_URL
        return api_key, base_url

    def _test_connection(self) -> None:
        api_key, base_url = self._current_creds()
        if not api_key:
            self._set_status("Ingresa una API key primero.", ok=False)
            return
        self._set_status("Conectando…", ok=None)
        try:
            client = PudumapsClient(api_key=api_key, base_url=base_url)
            projects = client.list_projects()
        except PudumapsError as e:
            msg = f"Error: {e}"
            if e.status == 401:
                msg += "\nKey inválida o revocada."
            elif e.status == 429:
                msg += "\nRate limit excedido. Intenta de nuevo en unos segundos."
            self._set_status(msg, ok=False)
            return
        except Exception as e:  # noqa: BLE001
            self._set_status(f"Error inesperado: {e}", ok=False)
            return
        self._set_status(
            f"✓ Conectado. {len(projects)} proyecto(s) disponible(s).", ok=True
        )

    def _save_and_close(self) -> None:
        api_key, base_url = self._current_creds()
        if not api_key:
            QMessageBox.warning(self, "Pudumaps", "La API key es obligatoria.")
            return
        try:
            save_credentials(api_key, base_url)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, "Pudumaps", f"No se pudo guardar la configuración:\n{e}"
            )
            return
        self.accept()

    def _clear(self) -> None:
        confirmed = QMessageBox.question(
            self,
            "Pudumaps",
            "¿Borrar las credenciales guardadas?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirmed != QMessageBox.Yes:
            return
        clear_credentials()
        self.api_key_edit.clear()
        self.base_url_edit.setText(DEFAULT_BASE_URL)
        self._set_status("Credenciales borradas.", ok=True)

    def _set_status(self, text: str, ok: bool | None) -> None:
        color = (
            "#22c55e" if ok is True else "#ef4444" if ok is False else "#888"
        )
        self.status_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        self.status_label.setText(text)
