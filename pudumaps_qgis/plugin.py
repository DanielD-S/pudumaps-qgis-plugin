from pathlib import Path

from qgis.core import QgsVectorLayer
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox

PLUGIN_DIR = Path(__file__).resolve().parent
ICONS_DIR = PLUGIN_DIR / "icons"
ICON_PATH = str(ICONS_DIR / "pudumaps-logo.png")  # main brand (menu entries)
ICON_SETTINGS = str(ICONS_DIR / "settings.svg")
ICON_DOWNLOAD = str(ICONS_DIR / "download.svg")
ICON_UPLOAD = str(ICONS_DIR / "upload.svg")
ICON_SYNC = str(ICONS_DIR / "sync.svg")


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
            icon_path=ICON_SETTINGS,
        )
        self._add_action(
            "Abrir proyecto…",
            self._open_projects,
            icon_path=ICON_DOWNLOAD,
        )
        self._add_action(
            "Subir capa activa a Pudumaps…",
            self._upload_active_layer,
            icon_path=ICON_UPLOAD,
        )
        self._add_action(
            "Sincronizar",
            self._sync_current,
            icon_path=ICON_SYNC,
        )
        # Context menu on the Layers Panel — "right-click on layer →
        # Subir a Pudumaps…". Uses QgsMapLayer.LayerType.VectorLayer from
        # the Qgis enum. Applies to all vector layers (existing + future).
        from qgis.core import QgsMapLayer

        self._context_action = QAction(
            QIcon(ICON_UPLOAD), "Subir a Pudumaps…", self.iface.mainWindow()
        )
        self._context_action.triggered.connect(self._upload_from_context)
        self.iface.addCustomActionForLayerType(
            self._context_action,
            "",  # no submenu — appears at top level of the context menu
            QgsMapLayer.VectorLayer,
            True,  # all vector layers
        )

    def unload(self) -> None:
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.toolbar.removeAction(action)
        try:
            self.iface.removeCustomActionForLayerType(self._context_action)
        except Exception:  # noqa: BLE001
            pass
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

    def _upload_active_layer(self) -> None:
        """Invoked from the menu/toolbar — uses the currently active layer."""
        layer = self.iface.activeLayer()
        self._launch_upload_for(layer)

    def _upload_from_context(self) -> None:
        """Invoked from the layer-panel context menu. QGIS sets the layer
        as 'active' right before firing the action, so we reuse the same
        entry point."""
        self._upload_active_layer()

    def _launch_upload_for(self, layer) -> None:
        if layer is None:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Pudumaps",
                "Selecciona primero una capa vectorial en el panel de capas.",
            )
            return
        if not isinstance(layer, QgsVectorLayer):
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Pudumaps",
                "Solo se pueden subir capas vectoriales a Pudumaps.",
            )
            return

        from .api_client import PudumapsClient
        from .auth import load_credentials
        from .dialogs.upload_dialog import UploadLayerDialog

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
                self.iface.mainWindow(), "Pudumaps", f"No se pudo crear el cliente: {e}"
            )
            return

        dlg = UploadLayerDialog(client, layer, self.iface.mainWindow())
        dlg.exec_()

    def _sync_current(self) -> None:
        """Sync the Pudumaps project referenced by the active layer (or
        the first Pudumaps-linked layer in the current QGIS project)."""
        from qgis.core import QgsProject

        from .api_client import PudumapsClient
        from .auth import load_credentials
        from .dialogs.sync_dialog import SyncDialog
        from .project_loader import PROP_PROJECT_ID, PROP_PROJECT_NAME

        # Find a Pudumaps-linked layer to discover the project id/name
        project_id = project_name = ""
        active = self.iface.activeLayer()
        if active is not None:
            project_id = active.customProperty(PROP_PROJECT_ID, "") or ""
            project_name = active.customProperty(PROP_PROJECT_NAME, "") or ""
        if not project_id:
            for layer in QgsProject.instance().mapLayers().values():
                pid = layer.customProperty(PROP_PROJECT_ID, "")
                if pid:
                    project_id = pid
                    project_name = (
                        layer.customProperty(PROP_PROJECT_NAME, "") or "(sin nombre)"
                    )
                    break

        if not project_id:
            QMessageBox.information(
                self.iface.mainWindow(),
                "Pudumaps",
                "No hay ninguna capa vinculada a un proyecto Pudumaps. "
                "Abre un proyecto primero o sube una capa.",
            )
            return

        creds = load_credentials()
        if not creds:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Pudumaps",
                "Configura tu API key primero.",
            )
            self._open_settings()
            return

        try:
            client = PudumapsClient(api_key=creds.api_key, base_url=creds.base_url)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self.iface.mainWindow(), "Pudumaps", f"No se pudo crear el cliente: {e}"
            )
            return

        dlg = SyncDialog(client, project_id, project_name or "(sin nombre)",
                         self.iface.mainWindow())
        dlg.exec_()

    # ── Helpers ──────────────────────────────────────────────────────────

    def _add_action(
        self,
        text: str,
        callback,
        enabled: bool = True,
        icon_path: str | None = None,
    ) -> QAction:
        icon = QIcon(icon_path or ICON_PATH)
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
