"""Sync dialog — shows the state of every layer in the project and
lets the user confirm or override the suggested action per layer."""

from __future__ import annotations

from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..api_client import PudumapsClient, PudumapsError
from ..exporter import ExportError, layer_to_geojson
from ..project_loader import (
    PROP_LAYER_ID,
    PROP_PROJECT_ID,
    PROP_PROJECT_NAME,
    apply_default_style,
    geojson_to_layer,
)
from ..styles import apply_pudumaps_style
from ..sync_manager import (
    LayerDiff,
    LayerState,
    SyncAction,
    SyncResult,
    canonical_hash,
    diff_project,
    stamp_hash,
)
from ..ui_helpers import build_header, separator

STATE_COLOR = {
    LayerState.UNCHANGED: ("Sin cambios", "#888"),
    LayerState.LOCAL_ONLY: ("Cambios locales", "#2563eb"),
    LayerState.REMOTE_ONLY: ("Cambios en servidor", "#b45309"),
    LayerState.CONFLICT: ("Conflicto", "#dc2626"),
    LayerState.NEW_LOCAL: ("Nueva local", "#16a34a"),
    LayerState.DELETED_REMOTE: ("Borrada en servidor", "#6b7280"),
}


class SyncDialog(QDialog):
    def __init__(
        self,
        client: PudumapsClient,
        project_id: str,
        project_name: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.client = client
        self.project_id = project_id
        self.project_name = project_name
        self.diffs: list[LayerDiff] = []

        self.setWindowTitle(f"Pudumaps — Sincronizar «{project_name}»")
        self.setMinimumSize(820, 500)
        apply_pudumaps_style(self)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Capa", "Estado", "Acción", "Detalle"])
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)

        self.progress = QProgressBar()
        self.progress.setVisible(False)

        self.status_label = QLabel("Analizando cambios…")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #888; font-size: 12px;")

        self.buttons = QDialogButtonBox()
        self.sync_btn = self.buttons.addButton(
            "Aplicar", QDialogButtonBox.AcceptRole
        )
        self.sync_btn.setEnabled(False)
        self.sync_btn.clicked.connect(self._apply)
        self.buttons.addButton(QDialogButtonBox.Close).clicked.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(
            build_header(
                "Sincronizar proyecto",
                f"«{project_name}» — revisa los cambios locales y remotos "
                "antes de aplicar.",
            )
        )
        layout.addWidget(separator())
        layout.addWidget(self.table)
        layout.addWidget(self.progress)
        layout.addWidget(self.status_label)
        layout.addWidget(self.buttons)
        self.setLayout(layout)

        # Load diffs async-ish (blocking but with yield points via processEvents)
        QApplication.processEvents()
        self._load_diffs()

    # ── Load ─────────────────────────────────────────────────────────────

    def _load_diffs(self) -> None:
        local_layers = self._collect_local_layers()
        try:
            self.diffs = diff_project(
                self.client,
                self.project_id,
                local_layers,
                local_hash_fn=self._compute_local_hashes,
            )
        except PudumapsError as e:
            self._set_status(f"Error: {e}", ok=False)
            return
        except Exception as e:  # noqa: BLE001
            self._set_status(f"Error inesperado: {e}", ok=False)
            return

        self._populate_table()
        counts = {s: 0 for s in LayerState}
        for d in self.diffs:
            counts[d.state] += 1
        summary_bits = [
            f"{counts[LayerState.LOCAL_ONLY]} push",
            f"{counts[LayerState.REMOTE_ONLY]} pull",
            f"{counts[LayerState.CONFLICT]} conflicto(s)",
            f"{counts[LayerState.NEW_LOCAL]} nueva(s)",
            f"{counts[LayerState.UNCHANGED]} sin cambios",
        ]
        self._set_status(" · ".join(summary_bits), ok=None)
        has_actionable = any(
            d.suggested_action != SyncAction.SKIP for d in self.diffs
        ) or any(d.state == LayerState.CONFLICT for d in self.diffs)
        self.sync_btn.setEnabled(has_actionable)

    def _collect_local_layers(self) -> list[QgsVectorLayer]:
        """All vector layers linked to this Pudumaps project (matching
        pudumaps/project_id custom property)."""
        result: list[QgsVectorLayer] = []
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            pid = layer.customProperty(PROP_PROJECT_ID, "")
            if pid == self.project_id:
                result.append(layer)
        return result

    def _compute_local_hashes(self, layer: QgsVectorLayer) -> tuple[str | None, str | None]:
        """Returns (current_hash, stored_last_hash)."""
        last_hash = layer.customProperty("pudumaps/last_hash", "") or None
        try:
            fc, _summary = layer_to_geojson(layer)
            return canonical_hash(fc), last_hash
        except ExportError:
            return None, last_hash
        except Exception:  # noqa: BLE001
            return None, last_hash

    # ── Populate table ───────────────────────────────────────────────────

    def _populate_table(self) -> None:
        self.table.setRowCount(len(self.diffs))
        for row, d in enumerate(self.diffs):
            self.table.setItem(row, 0, QTableWidgetItem(d.layer_name))

            state_text, color = STATE_COLOR[d.state]
            state_item = QTableWidgetItem(state_text)
            state_item.setForeground(_qcolor(color))
            self.table.setItem(row, 1, state_item)

            # Action combo
            combo = QComboBox()
            self._populate_combo(combo, d)
            self.table.setCellWidget(row, 2, combo)

            detail = self._detail_for(d)
            self.table.setItem(row, 3, QTableWidgetItem(detail))

    def _populate_combo(self, combo: QComboBox, d: LayerDiff) -> None:
        options = self._allowed_actions(d)
        for action, label in options:
            combo.addItem(label, action)
        # Pre-select the suggested action
        for idx in range(combo.count()):
            if combo.itemData(idx) == d.suggested_action:
                combo.setCurrentIndex(idx)
                break

    def _allowed_actions(self, d: LayerDiff) -> list[tuple[SyncAction, str]]:
        if d.state == LayerState.UNCHANGED:
            return [(SyncAction.SKIP, "Saltar")]
        if d.state == LayerState.LOCAL_ONLY:
            return [(SyncAction.PUSH, "Subir al servidor"), (SyncAction.SKIP, "Saltar")]
        if d.state == LayerState.REMOTE_ONLY:
            return [(SyncAction.PULL, "Descargar del servidor"), (SyncAction.SKIP, "Saltar")]
        if d.state == LayerState.CONFLICT:
            return [
                (SyncAction.SKIP, "Saltar — decido luego"),
                (SyncAction.USE_LOCAL, "Usar versión local (sube y sobrescribe servidor)"),
                (SyncAction.USE_REMOTE, "Usar versión servidor (descarga y sobrescribe local)"),
            ]
        if d.state == LayerState.NEW_LOCAL:
            return [(SyncAction.PUSH, "Subir como nueva"), (SyncAction.SKIP, "Saltar")]
        if d.state == LayerState.DELETED_REMOTE:
            return [
                (SyncAction.SKIP, "Mantener solo en local"),
                (SyncAction.DELETE_LOCAL, "Borrar capa local"),
            ]
        return [(SyncAction.SKIP, "Saltar")]

    def _detail_for(self, d: LayerDiff) -> str:
        if d.state == LayerState.CONFLICT:
            return "Ambos cambiaron desde último sync"
        if d.state == LayerState.LOCAL_ONLY:
            return "Hay ediciones locales sin subir"
        if d.state == LayerState.REMOTE_ONLY:
            return "Hay ediciones en el servidor sin bajar"
        if d.state == LayerState.NEW_LOCAL:
            return "Capa sin enlace a un layer_id remoto"
        if d.state == LayerState.DELETED_REMOTE:
            return "La capa ya no existe en Pudumaps"
        return ""

    # ── Apply ────────────────────────────────────────────────────────────

    def _apply(self) -> None:
        # Collect chosen actions from combos
        chosen: list[tuple[LayerDiff, SyncAction]] = []
        for row, d in enumerate(self.diffs):
            combo = self.table.cellWidget(row, 2)
            action = combo.currentData() if combo else SyncAction.SKIP
            chosen.append((d, action))

        actionable = [(d, a) for d, a in chosen if a != SyncAction.SKIP]
        if not actionable:
            QMessageBox.information(self, "Pudumaps", "No hay acciones que aplicar.")
            return

        self.sync_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setMaximum(len(actionable))
        self.progress.setValue(0)

        result = SyncResult()
        for idx, (d, action) in enumerate(actionable):
            self.progress.setValue(idx)
            self._set_status(f"[{idx + 1}/{len(actionable)}] {d.layer_name} → {action.value}", ok=None)
            QApplication.processEvents()
            try:
                self._dispatch(d, action, result)
            except PudumapsError as e:
                result.failed.append((d.layer_name, f"{e.code or 'api'}: {e}"))
            except Exception as e:  # noqa: BLE001
                result.failed.append((d.layer_name, f"unexpected: {e}"))

        self.progress.setValue(len(actionable))
        self._show_summary(result)

    def _dispatch(self, d: LayerDiff, action: SyncAction, result: SyncResult) -> None:
        if action == SyncAction.SKIP:
            result.skipped += 1
            return

        if action in (SyncAction.PUSH, SyncAction.USE_LOCAL):
            if d.layer_ref is None:
                raise RuntimeError("No hay capa local para subir")
            fc, _ = layer_to_geojson(d.layer_ref)
            name = d.layer_ref.name()
            if d.remote_id:
                self.client.update_layer(d.remote_id, name=name, geojson=fc)
            else:
                remote = self.client.upload_layer(self.project_id, name, fc)
                d.layer_ref.setCustomProperty(PROP_LAYER_ID, remote.id)
                d.layer_ref.setCustomProperty(PROP_PROJECT_ID, self.project_id)
                d.layer_ref.setCustomProperty(PROP_PROJECT_NAME, self.project_name)
            stamp_hash(d.layer_ref, canonical_hash(fc))
            result.pushed += 1
            return

        if action in (SyncAction.PULL, SyncAction.USE_REMOTE):
            if not d.remote_id:
                raise RuntimeError("No hay layer_id remoto para descargar")
            full = self.client.get_layer(d.remote_id)
            geojson = full.get("geojson") or {"type": "FeatureCollection", "features": []}
            if d.layer_ref is not None:
                # Replace features in-place on the existing QGIS layer
                _replace_layer_features(d.layer_ref, geojson)
                stamp_hash(d.layer_ref, canonical_hash(geojson))
            else:
                # Layer doesn't exist locally — create it in the same group
                new_layer = geojson_to_layer(
                    geojson,
                    name=full.get("name") or d.remote_name or "capa",
                    remote_layer_id=d.remote_id,
                    remote_project_id=self.project_id,
                    remote_project_name=self.project_name,
                )
                apply_default_style(new_layer)
                stamp_hash(new_layer, canonical_hash(geojson))
                QgsProject.instance().addMapLayer(new_layer, addToLegend=True)
            result.pulled += 1
            return

        if action == SyncAction.DELETE_LOCAL and d.layer_ref is not None:
            QgsProject.instance().removeMapLayer(d.layer_ref.id())
            result.skipped += 1

    def _show_summary(self, result: SyncResult) -> None:
        self.progress.setVisible(False)
        lines = [
            f"✓ {result.pushed} subida(s)",
            f"✓ {result.pulled} descarga(s)",
            f"{result.skipped} saltada(s)",
        ]
        if result.failed:
            lines.append("")
            lines.append(f"{len(result.failed)} fallada(s):")
            for name, err in result.failed:
                lines.append(f"  · {name}: {err}")
        msg = "\n".join(lines)
        if result.failed:
            self._set_status(msg, ok=False)
            QMessageBox.warning(self, "Pudumaps — Resultado sync", msg)
        else:
            self._set_status(msg, ok=True)
            QMessageBox.information(self, "Pudumaps — Resultado sync", msg)
        self._load_diffs()  # refresh table after sync

    # ── Status helper ────────────────────────────────────────────────────

    def _set_status(self, text: str, ok: bool | None) -> None:
        color = (
            "#22c55e" if ok is True else "#ef4444" if ok is False else "#888"
        )
        self.status_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        self.status_label.setText(text)


# ── Helpers ──────────────────────────────────────────────────────────────


def _qcolor(hexstr: str):
    from qgis.PyQt.QtGui import QColor

    return QColor(hexstr)


def _replace_layer_features(layer: QgsVectorLayer, geojson: dict) -> None:
    """In-place replace of all features in a memory-backed QgsVectorLayer."""
    from ..project_loader import geojson_to_layer

    # Build a transient layer from the new geojson just to steal its features
    src = geojson_to_layer(geojson, name="__sync_tmp__")
    pr = layer.dataProvider()
    layer.startEditing()
    # Wipe existing features
    ids = [f.id() for f in layer.getFeatures()]
    if ids:
        pr.deleteFeatures(ids)
    # Copy new features
    pr.addFeatures(list(src.getFeatures()))
    layer.commitChanges()
    layer.updateExtents()
    layer.triggerRepaint()
