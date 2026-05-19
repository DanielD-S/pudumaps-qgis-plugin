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
    """Descarga Sentinel-2 desde Microsoft Planetary Computer vía STAC.

    geoai 0.10 NO tiene built-in para esto. Implementamos directo usando
    `pystac-client` + `planetary-computer` (ambas deps de geoai, ya
    instaladas tras `Instalar módulo IA`).

    Pipeline:
    1. Query STAC collection `sentinel-2-l2a` en bbox + fecha + cloud cover.
    2. Toma la primera escena disponible (menor cloud cover).
    3. Firma la URL con planetary_computer.sign() (Auth opcional pero gratis).
    4. Lee R/G/B (bandas B04/B03/B02) con rioxarray, recortado al bbox.
    5. Apila las 3 bandas y exporta como GeoTIFF.
    """
    _emit(progress_cb, "Importando pystac-client + planetary-computer…")

    try:
        import planetary_computer  # type: ignore[import-not-found]
        from pystac_client import Client  # type: ignore[import-not-found]
    except ImportError as e:
        raise AIToolError(
            "Faltan dependencias para descarga Sentinel-2 "
            "(pystac-client / planetary-computer). Reinstala el módulo IA "
            "(Pudumaps → Instalar módulo IA…)."
        ) from e

    _emit(progress_cb, "Conectando a Microsoft Planetary Computer (STAC)…")
    catalog = Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )

    _emit(progress_cb, f"Buscando escenas Sentinel-2 L2A ({date_start} → {date_end}, ≤{cloud_max}% nubes)…")
    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=list(bbox),
        datetime=f"{date_start}/{date_end}",
        query={"eo:cloud_cover": {"lt": cloud_max}},
        max_items=10,
    )
    items = list(search.items())

    if not items:
        raise AIToolError(
            f"No se encontraron escenas Sentinel-2 para bbox {bbox} entre "
            f"{date_start} y {date_end} con ≤{cloud_max}% de nubes. "
            "Intenta ampliar fechas, subir cloud_max, o mover el bbox."
        )

    # Ordenar por cloud_cover ascendente, tomar la mejor.
    items.sort(key=lambda it: it.properties.get("eo:cloud_cover", 100))
    best = items[0]
    cloud = best.properties.get("eo:cloud_cover", "?")
    item_date = best.properties.get("datetime", "?")[:10]
    _emit(progress_cb, f"Mejor escena: {item_date} ({cloud}% nubes). Descargando bandas RGB…")

    # Bandas RGB de Sentinel-2: B04=red, B03=green, B02=blue.
    try:
        import rioxarray  # type: ignore[import-not-found]
        from rioxarray.merge import merge_arrays  # noqa: F401
    except ImportError as e:
        raise AIToolError(
            "Falta rioxarray para descarga Sentinel-2. Reinstala el módulo IA."
        ) from e

    band_assets = {"red": "B04", "green": "B03", "blue": "B02"}
    rasters = []
    for label, asset_key in band_assets.items():
        if asset_key not in best.assets:
            raise AIToolError(
                f"La escena Sentinel-2 no tiene asset '{asset_key}'. "
                "Reporta este caso — puede ser un problema del catálogo STAC."
            )
        url = best.assets[asset_key].href
        _emit(progress_cb, f"Descargando banda {label} ({asset_key})…")
        # `rioxarray.open_rasterio` con un URL firmado de PC funciona via vsicurl.
        da = rioxarray.open_rasterio(url, masked=True)
        # Recortar al bbox del usuario para no descargar la escena completa
        # (cada escena Sentinel-2 son ~100x100 km, ~700 MB sin recorte).
        da_clipped = da.rio.clip_box(
            minx=bbox[0], miny=bbox[1], maxx=bbox[2], maxy=bbox[3], crs="EPSG:4326"
        )
        rasters.append(da_clipped.squeeze())

    _emit(progress_cb, "Apilando RGB y guardando GeoTIFF…")
    # Apilar las 3 bandas en un raster multibanda.
    import xarray as xr  # type: ignore[import-not-found]

    stacked = xr.concat(rasters, dim="band")
    stacked = stacked.assign_coords(band=[1, 2, 3])
    stacked.rio.to_raster(output_path, driver="GTiff", compress="DEFLATE")


__all__ = ["DownloadSentinelTool"]
