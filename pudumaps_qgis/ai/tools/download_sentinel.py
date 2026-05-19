"""Descarga de imagen Sentinel-2 sobre un bbox y rango de fechas.

Usa el módulo de descarga de geoai-py (que internamente puede usar
planetary-computer o STAC público) para obtener una composición RGB
local que el usuario pueda usar como input a otras acciones IA.

`input_kind="none"`: no usa la capa activa. Todo el input viene del
diálogo (`DownloadSentinelDialog`).

Notas Chile:
- Sentinel-2 cubre todo el territorio chileno cada ~5 días (sin contar
  nubes). Para Atacama prácticamente nunca hay nubes; para Patagonia
  húmeda hay que ser permisivo con `cloud_max` o ampliar el rango.
- Las escenas Sentinel cubren ~100×100 km — si el bbox es grande el
  resultado puede tomar varios cientos de MB.
- El módulo geoai aplica el código UTM correspondiente. Para Chile el
  rango va de huso 18S (Arica) a 19S (la mayoría) a 12S (Magallanes).
"""

from __future__ import annotations

import os
from typing import Dict, Optional

from .base import AITool, AIToolError, ProgressCallback


class DownloadSentinelTool(AITool):
    id = "download_sentinel"
    name = "Descargar Sentinel-2"
    description = (
        "Descarga una composición RGB Sentinel-2 sobre el área visible "
        "del canvas (o un bbox custom) y rango de fechas indicado. "
        "El resultado se carga como raster en el proyecto QGIS."
    )
    requires = ["geoai"]
    input_kind = "none"
    output_suffix = ".tif"

    # ── No usa capa activa ──────────────────────────────────────────

    def validate_input(self, layer) -> Optional[str]:
        return None

    def prompt_params(self, parent=None, iface=None) -> Optional[Dict]:
        """Abre el diálogo de bbox + fechas + cloud cover."""
        from ...dialogs.download_sentinel_dialog import DownloadSentinelDialog

        dlg = DownloadSentinelDialog(iface=iface, parent=parent)
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

        bbox = params.get("bbox")
        date_start = params.get("date_start")
        date_end = params.get("date_end")
        cloud_max = params.get("cloud_max", 20)

        _validate_params(bbox, date_start, date_end, cloud_max)

        out_dir = os.path.dirname(os.path.abspath(output_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        _emit(progress_cb, "Cargando módulo geoai…")
        try:
            _run_geoai_download(
                bbox=bbox,
                date_start=date_start,
                date_end=date_end,
                cloud_max=cloud_max,
                output_path=output_path,
                progress_cb=progress_cb,
            )
        except AIToolError:
            raise
        except Exception as e:  # noqa: BLE001
            raise AIToolError(
                f"Falla al descargar Sentinel-2: {type(e).__name__}: {e}"
            ) from e

        if not os.path.exists(output_path):
            raise AIToolError(
                "geoai no produjo el archivo esperado. Probablemente no hay "
                "escenas Sentinel-2 que cumplan tu rango de fechas y nubosidad."
            )

        _emit(progress_cb, "Descarga completa.")
        return output_path


# ── Helpers privados ────────────────────────────────────────────────────


def _validate_params(bbox, date_start, date_end, cloud_max) -> None:
    """Levanta AIToolError con mensaje específico si algo está mal."""
    if not bbox or len(bbox) != 4:
        raise AIToolError(
            "Falta 'bbox' (xmin, ymin, xmax, ymax en EPSG:4326)."
        )
    try:
        xmin, ymin, xmax, ymax = (float(c) for c in bbox)
    except (TypeError, ValueError):
        raise AIToolError("bbox contiene valores no numéricos.")

    if xmin >= xmax or ymin >= ymax:
        raise AIToolError(
            f"bbox inválido: xmin({xmin}) debe ser < xmax({xmax}) e "
            f"ymin({ymin}) < ymax({ymax})."
        )
    # Chequeos defensivos: si el bbox abarca medio planeta, geoai va a
    # explotar antes de bajar nada. Mejor abortar acá con mensaje claro.
    width = xmax - xmin
    height = ymax - ymin
    if width > 5 or height > 5:
        raise AIToolError(
            "bbox demasiado grande (>5° de ancho o alto). Recorta el área "
            "antes de descargar — Sentinel-2 cubre tiles de ~1° y un bbox "
            "amplio genera descargas de GB."
        )

    if not date_start or not date_end:
        raise AIToolError("Faltan fechas: 'date_start' y 'date_end' obligatorias.")
    if date_start > date_end:
        raise AIToolError(
            f"date_start ({date_start}) debe ser anterior o igual a "
            f"date_end ({date_end})."
        )
    # Sentinel-2 inició operaciones el 2015-06-23.
    if date_end < "2015-06-23":
        raise AIToolError(
            "El rango pedido es anterior al lanzamiento de Sentinel-2 "
            "(2015-06-23). No hay imágenes disponibles."
        )

    try:
        cloud = int(cloud_max)
    except (TypeError, ValueError):
        raise AIToolError("cloud_max debe ser un entero entre 0 y 100.")
    if not 0 <= cloud <= 100:
        raise AIToolError(f"cloud_max fuera de rango: {cloud}. Debe ser 0-100.")


def _emit(cb: Optional[ProgressCallback], msg: str) -> None:
    if cb is None:
        return
    try:
        cb(msg)
    except Exception:  # noqa: BLE001
        pass


def _run_geoai_download(
    bbox,
    date_start: str,
    date_end: str,
    cloud_max: int,
    output_path: str,
    progress_cb: Optional[ProgressCallback],
) -> None:
    """Aísla la llamada a la API de descarga de geoai.

    geoai-py 0.10.x suele exponer `download_sentinel2` o
    `download_sentinel`. Intentamos ambos para resistir variaciones.
    """
    _emit(progress_cb, "Importando geoai…")
    import geoai  # noqa: F401

    fn = (
        getattr(geoai, "download_sentinel2", None)
        or getattr(geoai, "download_sentinel", None)
    )
    if fn is None:
        raise AIToolError(
            "Esta versión de geoai no expone download_sentinel2() ni "
            "download_sentinel(). Verifica que geoai-py==0.10.0 esté "
            "instalado (Pudumaps → Instalar módulo IA…)."
        )

    _emit(progress_cb, f"Consultando catálogo Sentinel-2 ({date_start} → {date_end})…")
    fn(
        bbox=tuple(bbox),
        start_date=date_start,
        end_date=date_end,
        max_cloud_cover=cloud_max,
        output_path=output_path,
    )


__all__ = ["DownloadSentinelTool"]
