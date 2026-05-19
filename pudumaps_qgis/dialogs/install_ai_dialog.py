"""Diálogo de instalación de dependencias de IA.

Pregunta al usuario si quiere instalar `geoai-py` (y opcionalmente
`GeoAgent`), explicando tamaños y prerequisitos. Si confirma, ejecuta
la instalación en un QThread y muestra progreso vía QProgressDialog.

La instalación no congela QGIS: el thread captura stdout de pip línea
a línea y la emite como signal al hilo del UI.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from qgis.PyQt.QtCore import Qt, QThread, QTimer, pyqtSignal
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
from ..ai.pip_progress import PipProgressParser
from ..error_utils import log_full_error, safe_error_message
from ..styles import apply_pudumaps_style
from ..ui_helpers import build_header, separator


class _InstallWorker(QThread):
    """Worker thread que ejecuta una secuencia de install_package().

    Cada tupla en `packages` es (name, version, extras, index_url) — el
    index_url permite forzar PyTorch CPU-only desde el índice de PyTorch
    (https://download.pytorch.org/whl/cpu) en vez del default PyPI que
    puede pedir variantes CUDA que no funcionan sin GPU NVIDIA + drivers.

    Emite `line` por cada línea de stdout y `finished_with_results` al
    terminar con la lista completa de InstallResult.
    """

    line = pyqtSignal(str)
    finished_with_results = pyqtSignal(list)

    def __init__(self, packages: List[Tuple[str, str, Optional[str], Optional[str]]]):
        """packages = [(name, version, extras, index_url), ...]"""
        super().__init__()
        self._packages = packages
        self._results: List[InstallResult] = []

    def run(self) -> None:
        for name, version, extras, index_url in self._packages:
            label = f"{name}=={version}" if version else name
            self.line.emit(f"→ Instalando {label}…")
            try:
                result = install_package(
                    package=name,
                    version=version,
                    extras=extras,
                    index_url=index_url,
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

        # Cleanup post-instalación: desinstalar pyarrow si quedó instalado.
        # Su `lib.pyd` choca con DLLs C++ de QGIS y causa
        # "DLL load failed while importing lib" al hacer `import geoai`
        # desde el plugin. sklearn lo importa defensivamente y cae sin él
        # — no afecta funcionalidad de las acciones IA. Documentado en
        # docs/modelos-chile.md.
        if any(r.success for r in self._results):
            self._cleanup_pyarrow()

        self.finished_with_results.emit(self._results)

    def _cleanup_pyarrow(self) -> None:
        """Best-effort uninstall de pyarrow tras instalar geoai/GeoAgent.

        Si pyarrow no está instalado, pip lo skipea sin error. Si falla
        por permisos u otra razón, solo loggeamos — no abortamos.
        """
        self.line.emit("→ Limpiando pyarrow (causa DLL conflict con QGIS)…")
        try:
            from ..ai.installer import qgis_python_executable
            import subprocess as _subprocess

            _subprocess.run(  # noqa: S603
                [
                    qgis_python_executable(),
                    "-m",
                    "pip",
                    "uninstall",
                    "-y",
                    "--disable-pip-version-check",
                    "pyarrow",
                ],
                capture_output=True,
                timeout=60,
            )
        except Exception as e:  # noqa: BLE001
            log_full_error("install_ai_dialog._cleanup_pyarrow", e)


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
            "<li>La descarga toma <b>10-30 minutos</b> según tu conexión "
            "(~500 MB de PyTorch + dependencias).</li>"
            "<li>En Windows: instala <i>Microsoft Visual C++ Redistributable</i> "
            "si no lo tienes (PyTorch lo necesita).</li>"
            "<li>Conexión a internet estable durante toda la descarga.</li>"
            "<li>Cierra otros plugins que usen Python intensivamente.</li>"
            "<li><b>Si aparece una ventana de consola negra: NO la cierres</b> — "
            "es pip mostrando progreso. Se cierra sola al terminar.</li>"
            "</ul>"
            "<small>Las dependencias se instalan en tu perfil de usuario "
            "(<code>pip install --user</code>) — no requieren permisos "
            "de administrador. Mientras descarga, el progreso aparece "
            "tanto aquí abajo como en la ventana de consola si llega a "
            "abrirse.</small>"
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

    # Índice oficial de PyTorch para wheels CPU-only. Usar este en vez del
    # default PyPI evita el caso típico Windows en que pip baja una variante
    # CUDA y al `import torch` falla con DLL load failed (busca CUDA y
    # no la encuentra, o choca con DLLs de QGIS).
    _PYTORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"

    def _selected_packages(self) -> list[tuple[str, str | None, str | None, str | None]]:
        """Devuelve la secuencia de instalaciones a correr.

        Cuando se instala geoai-py o GeoAgent, se INSTALA PRIMERO torch
        CPU-only desde el índice de PyTorch. Así cuando pip resuelve las
        deps de geoai, ve que torch ya está instalado (en la versión
        adecuada) y no intenta reinstalar la variante problemática.

        Formato: [(name, version, extras, index_url), ...].
        """
        packages: list[tuple[str, str | None, str | None, str | None]] = []
        needs_torch = (
            (self.cb_geoai.isChecked() and self.cb_geoai.isEnabled())
            or (self.cb_geoagent.isChecked() and self.cb_geoagent.isEnabled())
        )
        # Si no hay nada que instale geoai, no metas torch — sería desperdicio.
        if needs_torch:
            # Sin version pin: dejamos que el índice CPU elija la última
            # compatible con el Python embebido. Forzar versión específica
            # aumenta el riesgo de "no wheel para esta Python.minor".
            packages.append(("torch", None, None, self._PYTORCH_CPU_INDEX))
            packages.append(("torchvision", None, None, self._PYTORCH_CPU_INDEX))

        if self.cb_geoai.isChecked() and self.cb_geoai.isEnabled():
            packages.append((GEOAI_PACKAGE, GEOAI_PINNED_VERSION, None, None))
        if self.cb_geoagent.isChecked() and self.cb_geoagent.isEnabled():
            # Ollama + integración geoai en un solo install.
            packages.append((GEOAGENT_PACKAGE, GEOAGENT_PINNED_VERSION, "ollama,geoai", None))
        return packages

    def _on_install(self) -> None:
        packages = self._selected_packages()
        if not packages:
            QMessageBox.information(
                self, "Pudumaps", "Selecciona al menos un paquete para instalar."
            )
            return

        # Estimado dinámico: geoai solo = ~35 paquetes; +GeoAgent = ~45.
        # +5 si también vamos a instalar torch+torchvision al inicio.
        estimate = 35
        if any(p[0] == GEOAGENT_PACKAGE for p in packages):
            estimate = 45
        if any(p[0] == "torch" for p in packages):
            estimate += 5

        progress = QProgressDialog(
            "Preparando instalación…",
            "Cancelar",
            0,
            100,  # determinate
            self,
        )
        progress.setWindowTitle("Pudumaps — Instalando IA")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)

        # Parser de líneas de pip → progreso estructurado.
        parser = PipProgressParser(estimate=estimate)

        # Contador de tiempo transcurrido: QTimer cada segundo.
        # Usamos atributo en el worker para que el callback persista.
        import time

        start_ts = time.monotonic()
        elapsed_timer = QTimer(progress)
        elapsed_timer.setInterval(1000)

        def update_label() -> None:
            snap = parser.snapshot
            elapsed_s = int(time.monotonic() - start_ts)
            mm, ss = divmod(elapsed_s, 60)
            time_str = f"{mm:02d}:{ss:02d}"
            last = snap.last_line
            if len(last) > 70:
                last = "…" + last[-69:]
            progress.setLabelText(
                f"{snap.human_summary} · tiempo {time_str}\n{last}"
            )

        elapsed_timer.timeout.connect(update_label)
        elapsed_timer.start()

        worker = _InstallWorker(packages)

        def on_line(text: str) -> None:
            parser.feed(text)
            snap = parser.snapshot
            progress.setValue(snap.percent)
            update_label()

        def on_done(results: list[InstallResult]) -> None:
            elapsed_timer.stop()
            progress.setValue(100)
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
