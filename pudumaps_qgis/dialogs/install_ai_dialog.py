"""Diálogo de instalación de dependencias de IA.

Pregunta al usuario si quiere instalar `geoai-py` (y opcionalmente
`GeoAgent`), explicando tamaños y prerequisitos. Si confirma, ejecuta
la instalación en un QThread y muestra progreso vía QProgressDialog.

La instalación no congela QGIS: el thread captura stdout de pip línea
a línea y la emite como signal al hilo del UI.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QVBoxLayout,
)

from ..ai import (
    GEOAGENT_PACKAGE,
    GEOAGENT_PINNED_VERSION,
    GEOAI_PACKAGE,
    GEOAI_PINNED_VERSION,
    is_geoagent_available,
    is_geoai_available,
)
from ..ai.installer import InstallResult, install_package
from ..error_utils import log_full_error, safe_error_message
from ..styles import apply_pudumaps_style
from ..ui_helpers import build_header, separator


class _InstallWorker(QThread):
    """Worker thread que ejecuta una secuencia de install_package().

    Emite `line` por cada línea de stdout y `finished_with_results` al
    terminar con la lista completa de InstallResult.
    """

    line = pyqtSignal(str)
    finished_with_results = pyqtSignal(list)

    def __init__(self, packages: List[Tuple[str, str, Optional[str]]]):
        """packages = [(name, version, extras), ...]"""
        super().__init__()
        self._packages = packages
        self._results: List[InstallResult] = []

    def run(self) -> None:
        for name, version, extras in self._packages:
            self.line.emit(f"→ Instalando {name}=={version}…")
            try:
                result = install_package(
                    package=name,
                    version=version,
                    extras=extras,
                    progress_cb=lambda l: self.line.emit(l),
                )
            except Exception as e:  # noqa: BLE001
                # Defensa: install_package debería atrapar todo, pero
                # si algo se escapa convertimos a result fallido.
                log_full_error(f"install_ai_dialog._InstallWorker({name})", e)
                result = InstallResult(
                    package=name,
                    version=version,
                    success=False,
                    exit_code=-3,
                    output="",
                    error_message=safe_error_message(e),
                )
            self._results.append(result)
            if not result.success:
                # No seguir con el resto si uno falla.
                break
        self.finished_with_results.emit(self._results)


class InstallAIDialog(QDialog):
    """Modal que ofrece instalar las deps de IA.

    Usage:
        dlg = InstallAIDialog(parent=iface.mainWindow())
        if dlg.exec_() == QDialog.Accepted:
            # algún paquete fue instalado correctamente
            ...
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pudumaps — Instalar módulo IA")
        self.setMinimumWidth(560)
        apply_pudumaps_style(self)

        self._installed_anything = False

        intro = QLabel(
            "El módulo IA agrega detección de edificaciones, cuerpos de "
            "agua, clasificación de uso de suelo y descarga de imágenes "
            "Sentinel — todo corre localmente en tu PC.\n\n"
            "Selecciona qué instalar:"
        )
        intro.setWordWrap(True)

        self.cb_geoai = QCheckBox(
            f"Motor de visión (geoai-py {GEOAI_PINNED_VERSION}) — "
            "~500 MB descarga, ~2 GB en disco"
        )
        self.cb_geoai.setChecked(not is_geoai_available())
        self.cb_geoai.setEnabled(not is_geoai_available())
        if is_geoai_available():
            self.cb_geoai.setText(self.cb_geoai.text() + "  ✓ ya instalado")

        self.cb_geoagent = QCheckBox(
            f"Asistente conversacional (GeoAgent {GEOAGENT_PINNED_VERSION}) — "
            "+~50 MB, requiere Ollama instalado aparte"
        )
        self.cb_geoagent.setChecked(False)
        self.cb_geoagent.setEnabled(not is_geoagent_available())
        if is_geoagent_available():
            self.cb_geoagent.setText(self.cb_geoagent.text() + "  ✓ ya instalado")

        warn = QLabel(
            "<b>Antes de continuar:</b>"
            "<ul>"
            "<li>En Windows: instala <i>Microsoft Visual C++ Redistributable</i> "
            "si no lo tienes (PyTorch lo necesita).</li>"
            "<li>Conexión a internet estable durante la descarga.</li>"
            "<li>Cierra otros plugins que usen Python intensivamente.</li>"
            "</ul>"
            "<small>Las dependencias se instalan en tu perfil de usuario "
            "(<code>pip install --user</code>) — no requieren permisos "
            "de administrador.</small>"
        )
        warn.setWordWrap(True)
        warn.setTextFormat(Qt.RichText)
        warn.setStyleSheet("color: #555; font-size: 12px;")

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.buttons.button(QDialogButtonBox.Ok).setText("Instalar")
        self.buttons.accepted.connect(self._on_install)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(
            build_header(
                "Instalar módulo IA",
                "Dependencias opcionales para análisis local con IA.",
            )
        )
        layout.addWidget(separator())
        layout.addWidget(intro)
        layout.addWidget(self.cb_geoai)
        layout.addWidget(self.cb_geoagent)
        layout.addWidget(separator())
        layout.addWidget(warn)
        layout.addWidget(self.buttons)
        self.setLayout(layout)

    # ── Logic ────────────────────────────────────────────────────────────

    def installed_anything(self) -> bool:
        """True si al menos una instalación se completó correctamente."""
        return self._installed_anything

    def _selected_packages(self) -> list[tuple[str, str, str | None]]:
        packages: list[tuple[str, str, str | None]] = []
        if self.cb_geoai.isChecked() and self.cb_geoai.isEnabled():
            packages.append((GEOAI_PACKAGE, GEOAI_PINNED_VERSION, None))
        if self.cb_geoagent.isChecked() and self.cb_geoagent.isEnabled():
            # Ollama + integración geoai en un solo install.
            packages.append((GEOAGENT_PACKAGE, GEOAGENT_PINNED_VERSION, "ollama,geoai"))
        return packages

    def _on_install(self) -> None:
        packages = self._selected_packages()
        if not packages:
            QMessageBox.information(
                self, "Pudumaps", "Selecciona al menos un paquete para instalar."
            )
            return

        progress = QProgressDialog(
            "Preparando instalación…",
            "Cancelar",
            0,
            0,  # indeterminate
            self,
        )
        progress.setWindowTitle("Pudumaps — Instalando IA")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)

        worker = _InstallWorker(packages)

        def on_line(text: str) -> None:
            # Mostrar solo las últimas ~80 chars para que el dialog no
            # se estire indefinidamente.
            shown = text if len(text) <= 80 else "…" + text[-79:]
            progress.setLabelText(shown)

        def on_done(results: list[InstallResult]) -> None:
            progress.close()
            self._show_summary(results)
            worker.deleteLater()

        worker.line.connect(on_line)
        worker.finished_with_results.connect(on_done)
        progress.canceled.connect(worker.terminate)

        worker.start()
        progress.exec_()

    def _show_summary(self, results: list[InstallResult]) -> None:
        ok = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        self._installed_anything = bool(ok)

        if failed:
            details = "\n".join(
                f"• {r.package}: {r.error_message or 'error desconocido'}"
                for r in failed
            )
            QMessageBox.critical(
                self,
                "Pudumaps · Instalación con errores",
                f"Algunos paquetes fallaron:\n\n{details}\n\n"
                "Revisa la conexión y reintenta. Si persiste, "
                "consulta docs/ai-tools.md.",
            )
            # Si al menos uno se instaló, cerramos como Accepted; si no, rejected.
            if ok:
                self.accept()
            else:
                self.reject()
            return

        QMessageBox.information(
            self,
            "Pudumaps",
            "Instalación completa. Reinicia QGIS o recarga el plugin "
            "para activar las acciones de IA.",
        )
        self.accept()
