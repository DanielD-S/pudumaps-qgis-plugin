from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox

PLUGIN_DIR = Path(__file__).resolve().parent
ICON_PATH = str(PLUGIN_DIR / "icons" / "pudumaps.svg")


class PudumapsPlugin:
    """Main plugin class — wires the QGIS UI to the Pudumaps API client."""

    def __init__(self, iface):
        self.iface = iface
        self.menu = "&Pudumaps"
        self.actions: list[QAction] = []
        self.toolbar = self.iface.addToolBar("Pudumaps")
        self.toolbar.setObjectName("PudumapsToolbar")

    # ── Entry / exit ─────────────────────────────────────────────────────

    def initGui(self) -> None:
        self._add_action(
            "Configuración…",
            self._open_settings,
            enabled=True,
        )
        self._add_action(
            "Abrir proyecto…",
            self._open_projects,
            enabled=True,
        )
        self._add_action(
            "Sincronizar",
            self._sync_current,
            enabled=True,
        )

    def unload(self) -> None:
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.toolbar.removeAction(action)
        del self.toolbar

    # ── Actions ──────────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        from .dialogs.settings_dialog import SettingsDialog

        dlg = SettingsDialog(self.iface.mainWindow())
        dlg.exec_()

    def _open_projects(self) -> None:
        from .api_client import PudumapsClient
        from .auth import load_credentials
        from .dialogs.projects_dialog import ProjectsDialog

        creds = load_credentials()
        if not creds:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Pudumaps",
                "No hay credenciales configuradas. Abre Configuración primero.",
            )
            self._open_settings()
            return

        try:
            client = PudumapsClient(api_key=creds.api_key, base_url=creds.base_url)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Pudumaps",
                f"No se pudo crear el cliente: {e}",
            )
            return

        dlg = ProjectsDialog(client, self.iface.mainWindow())
        dlg.exec_()

    def _sync_current(self) -> None:
        # Fase 4 — proximamente
        QMessageBox.information(
            self.iface.mainWindow(),
            "Pudumaps",
            "Sincronizar estará disponible en la próxima versión (Fase 4).",
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    def _add_action(self, text: str, callback, enabled: bool = True) -> QAction:
        icon = QIcon(ICON_PATH)
        action = QAction(icon, text, self.iface.mainWindow())
        action.triggered.connect(callback)
        action.setEnabled(enabled)
        self.iface.addPluginToMenu(self.menu, action)
        self.toolbar.addAction(action)
        self.actions.append(action)
        return action

    @staticmethod
    def tr(message: str) -> str:
        return QCoreApplication.translate("Pudumaps", message)
