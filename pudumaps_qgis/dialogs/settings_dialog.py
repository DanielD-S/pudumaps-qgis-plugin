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
from ..auth import (
    PlaintextStorageRefused,
    clear_credentials,
    is_encrypted_storage_available,
    load_credentials,
    save_credentials,
)
from ..error_utils import log_full_error, safe_error_message
from ..styles import apply_pudumaps_style
from ..ui_helpers import build_header, separator
from ..url_validator import InvalidBaseUrlError, validate_base_url


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
        try:
            base_url = validate_base_url(base_url)
        except InvalidBaseUrlError as e:
            self._set_status(safe_error_message(e), ok=False)
            return
        self._set_status("Conectando…", ok=None)
        try:
            client = PudumapsClient(api_key=api_key, base_url=base_url)
            projects = client.list_projects()
        except PudumapsError as e:
            msg = f"Error: {safe_error_message(e)}"
            if e.status == 401:
                msg += "\nKey inválida o revocada."
            elif e.status == 429:
                msg += "\nRate limit excedido. Intenta de nuevo en unos segundos."
            self._set_status(msg, ok=False)
            return
        except Exception as e:  # noqa: BLE001
            log_full_error("settings_dialog._test_connection", e)
            self._set_status(
                f"Error inesperado: {safe_error_message(e)}", ok=False
            )
            return
        self._set_status(
            f"✓ Conectado. {len(projects)} proyecto(s) disponible(s).", ok=True
        )

    def _save_and_close(self) -> None:
        api_key, base_url = self._current_creds()
        if not api_key:
            QMessageBox.warning(self, "Pudumaps", "La API key es obligatoria.")
            return
        # H2 ALTO: validamos HTTPS antes de guardar (evita persistir un
        # http:// que después leakearía la key en cada request).
        try:
            base_url = validate_base_url(base_url)
        except InvalidBaseUrlError as e:
            QMessageBox.warning(self, "Pudumaps · URL inválida",
                                safe_error_message(e))
            return

        # H1 ALTO: si QgsAuthManager no está listo, advertir explícitamente
        # antes de caer al fallback plaintext de QSettings.
        allow_plaintext = False
        if not is_encrypted_storage_available():
            allow_plaintext = self._confirm_plaintext_fallback()
            if not allow_plaintext:
                return

        try:
            save_credentials(
                api_key, base_url,
                allow_plaintext_fallback=allow_plaintext,
            )
        except PlaintextStorageRefused as e:
            # No debería ocurrir porque ya pedimos confirmación, pero
            # protege ante race con cambios del auth manager.
            QMessageBox.warning(self, "Pudumaps", safe_error_message(e))
            return
        except Exception as e:  # noqa: BLE001
            log_full_error("settings_dialog._save_and_close", e)
            QMessageBox.critical(
                self, "Pudumaps",
                f"No se pudo guardar la configuración:\n{safe_error_message(e)}",
            )
            return
        self.accept()

    def _confirm_plaintext_fallback(self) -> bool:
        """Pregunta al user si acepta guardar la API key sin cifrar.

        Returns True si confirmó, False si canceló.
        """
        reply = QMessageBox.warning(
            self,
            "Pudumaps · Almacenamiento sin cifrar",
            "QGIS no tiene un master password configurado, así que la "
            "API key se guardará en plaintext en QSettings.\n\n"
            "Recomendado: cancela, abre QGIS → Configuración → "
            "Opciones → Autenticación, configura un master password, "
            "y vuelve a guardar.\n\n"
            "¿Continuar guardando sin cifrar?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return reply == QMessageBox.Yes

    def _clear(self) -> None:
        confirmed = QMessageBox.question(
            self,
            "Pudumaps",
            "¿Borrar las credenciales guardadas?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirmed != QMessageBox.Yes:
            return
        auth_cleared = clear_credentials()
        self.api_key_edit.clear()
        self.base_url_edit.setText(DEFAULT_BASE_URL)
        if auth_cleared:
            self._set_status("Credenciales borradas.", ok=True)
        else:
            # H8: aviso explícito si la entry cifrada no se pudo borrar.
            self._set_status(
                "Credenciales locales borradas. La entry cifrada en "
                "QgsAuthManager no se pudo eliminar — abre QGIS → "
                "Configuración → Opciones → Autenticación y borrala "
                "manualmente (busca 'pudumaps-api').",
                ok=False,
            )

    def _set_status(self, text: str, ok: bool | None) -> None:
        color = (
            "#22c55e" if ok is True else "#ef4444" if ok is False else "#888"
        )
        self.status_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        self.status_label.setText(text)
