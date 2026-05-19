"""Detección de cambios entre dos rásters usando geoai/torchange.

Toma dos rásters del mismo bbox y distinta fecha y produce un raster
máscara binario (1 = cambio detectado, 0 = sin cambio). Útil para:
- Detección de deforestación pre/post incendio.
- Cambios en infraestructura urbana (nuevas edificaciones).
- Monitoreo de retroceso glaciar / lagos.

Como no hay "capa activa" canónica, esta tool usa `input_kind="none"` y
pide los dos rásters al usuario vía `prompt_params()` con un diálogo
custom (`dialogs/change_detection_dialog.py`).

Caveats Chile:
- Sentinel-2 (10 m/px) detecta cambios >100 m². Para escala fina usar
  ortofoto + recortar al área de interés.
- En zonas montañosas las sombras cambian con la fecha — pueden generar
  falsos positivos. Usar rásters con ángulo solar similar (mismo mes).
- Los modelos pre-entrenados de torchange son generalistas; para
  deforestación bosque nativo chileno habrá que finetunear en v0.8.
"""

from __future__ import annotations

import os
from typing import Dict, Optional

from .base import AITool, AIToolError, ProgressCallback


class ChangeDetectionTool(AITool):
    id = "change_detection"
    name = "Detectar cambios (2 rásters)"
    description = (
        "Compara dos rásters del mismo bbox y produce una máscara "
        "binaria de cambio. Útil para monitoreo temporal: deforestación, "
        "expansión urbana, retroceso glaciar."
    )
    requires = ["geoai"]
    input_kind = "none"  # los dos rásters vienen vía prompt_params
    output_suffix = ".tif"

    # ── Validación / params ─────────────────────────────────────────

    def validate_input(self, layer) -> Optional[str]:
        # No usamos la capa activa. Siempre OK.
        return None

    def prompt_params(self, parent=None, iface=None) -> Optional[Dict]:
        """Abre el diálogo selector de los dos rásters.

        Import lazy: el diálogo importa Qt, así que solo se carga cuando
        el panel efectivamente abre la acción — los tests sin Qt no
        necesitan instanciarlo.
        """
        from ...dialogs.change_detection_dialog import ChangeDetectionDialog

        dlg = ChangeDetectionDialog(iface=iface, parent=parent)
        if dlg.exec_() != dlg.Accepted:
            return None
        return dlg.result_params()

    # ── Ejecución ───────────────────────────────────────────────────

    def run(
        self,
        raster_path: str,
        output_path: str,
        params: Optional[Dict] = None,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> str:
        self.ensure_available()
        params = params or {}
        before = params.get("raster_before")
        after = params.get("raster_after")
        if not before or not after:
            raise AIToolError(
                "Faltan parámetros: 'raster_before' y 'raster_after' son obligatorios."
            )
        if before == after:
            raise AIToolError("Los dos rásters son el mismo archivo.")
        for label, path in (("antes", before), ("después", after)):
            if not os.path.exists(path):
                raise AIToolError(f"No existe el raster '{label}': {path}")

        out_dir = os.path.dirname(os.path.abspath(output_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        _emit(progress_cb, "Cargando módulo geoai…")

        try:
            _run_geoai_change(
                raster_before=before,
                raster_after=after,
                output_path=output_path,
                progress_cb=progress_cb,
            )
        except AIToolError:
            raise
        except Exception as e:  # noqa: BLE001
            raise AIToolError(
                f"Falla al ejecutar geoai/torchange: {type(e).__name__}: {e}"
            ) from e

        _emit(progress_cb, "Listo: máscara de cambios generada.")
        return output_path


def _emit(cb: Optional[ProgressCallback], msg: str) -> None:
    if cb is None:
        return
    try:
        cb(msg)
    except Exception:  # noqa: BLE001
        pass


def _run_geoai_change(
    raster_before: str,
    raster_after: str,
    output_path: str,
    progress_cb: Optional[ProgressCallback],
) -> None:
    """Aísla la llamada a la API de geoai/torchange.

    Si el módulo evoluciona, este es el único lugar a modificar.
    """
    _emit(progress_cb, "Importando geoai/torchange…")
    import geoai  # noqa: F401

    detector = None
    try:
        from geoai import ChangeDetector  # type: ignore[attr-defined]
        detector = ChangeDetector()
    except (ImportError, AttributeError):
        pass

    if detector is not None and hasattr(detector, "predict"):
        _emit(progress_cb, "Ejecutando inferencia de cambios…")
        detector.predict(
            raster_before, raster_after, output_path=output_path
        )
        return

    fn = (
        getattr(geoai, "detect_changes", None)
        or getattr(geoai, "change_detection", None)
    )
    if fn is None:
        raise AIToolError(
            "Esta versión de geoai no expone ChangeDetector ni "
            "detect_changes(). Verifica que geoai-py==0.10.0 esté "
            "instalado (Pudumaps → Instalar módulo IA…)."
        )
    _emit(progress_cb, "Ejecutando inferencia de cambios…")
    fn(raster_before, raster_after, output_path=output_path)


__all__ = ["ChangeDetectionTool"]
