"""Detección de cuerpos de agua sobre raster RGB usando geoai.

Wrapper del modelo de water-body extraction de geoai-py. Toma un
raster RGB (3+ bandas) y produce polígonos GeoJSON de cuerpos de agua
(lagos, ríos, embalses, salares con espejo de agua).

Notas Chile:
- Funciona bien con imagen Sentinel-2 sobre lagos andinos (Llanquihue,
  Ranco, Todos los Santos) y embalses centrales (Rapel, Colbún).
- Para ríos angostos (<10 m de ancho a 10 m/px) detecta solo el cauce
  principal. Use ortofoto de mayor resolución para hidrografía fina.
- En salares (Atacama, Surire), detecta solo las lagunas con espejo de
  agua superficial, no la costra salina.
"""

from __future__ import annotations

import os
from typing import Dict, Optional

from .base import AITool, AIToolError, ProgressCallback


class ExtractWaterTool(AITool):
    id = "extract_water"
    name = "Detectar cuerpos de agua"
    description = (
        "Segmenta lagos, ríos, embalses y lagunas sobre un raster RGB. "
        "Funciona con ortofoto y con imagen satelital Sentinel-2 / Landsat."
    )
    requires = ["geoai"]
    input_kind = "raster"

    # ── Validación de input ─────────────────────────────────────────

    def validate_input(self, layer) -> Optional[str]:
        if layer is None:
            return "Selecciona primero una capa raster en QGIS."
        if not hasattr(layer, "bandCount"):
            return "Esta acción requiere una capa raster, no vectorial."
        try:
            bands = int(layer.bandCount())
        except Exception:  # noqa: BLE001
            return "No se pudo leer el número de bandas del raster."
        if bands < 3:
            return (
                f"El raster tiene {bands} banda(s); se requieren al menos 3 "
                "(R, G, B). Carga una ortofoto o composición RGB."
            )
        source = getattr(layer, "source", None)
        if callable(source) and not source():
            return "El raster no tiene archivo en disco asociado."
        return None

    # ── Ejecución ───────────────────────────────────────────────────

    def run(
        self,
        raster_path: str,
        output_path: str,
        params: Optional[Dict] = None,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> str:
        self.ensure_available()
        _emit(progress_cb, "Cargando módulo geoai…")

        if not os.path.exists(raster_path):
            raise AIToolError(f"No existe el raster: {raster_path}")

        out_dir = os.path.dirname(os.path.abspath(output_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        try:
            polygons = _run_geoai_water(
                raster_path=raster_path,
                output_path=output_path,
                progress_cb=progress_cb,
            )
        except AIToolError:
            raise
        except Exception as e:  # noqa: BLE001
            raise AIToolError(
                f"Falla al ejecutar geoai: {type(e).__name__}: {e}"
            ) from e

        _emit(progress_cb, f"Listo: {polygons} cuerpo(s) de agua detectado(s).")
        return output_path


def _emit(cb: Optional[ProgressCallback], msg: str) -> None:
    if cb is None:
        return
    try:
        cb(msg)
    except Exception:  # noqa: BLE001
        pass


def _run_geoai_water(
    raster_path: str,
    output_path: str,
    progress_cb: Optional[ProgressCallback],
) -> int:
    """Llamada real a la API de geoai 0.10.x.

    geoai 0.10 NO tiene un `WaterBodyExtractor` dedicado. La forma
    soportada es usar `CLIPSegmentation` con text prompt:
    `segment_image(input_path, output_path, text_prompt="water bodies, lakes, rivers")`.

    Bajo el capó usa CLIP-Seg (Hugging Face), pre-entrenado en imágenes
    naturales — funciona razonable sobre orto RGB y Sentinel-2 RGB.
    Descarga el modelo (~600 MB) la primera vez.
    """
    _emit(progress_cb, "Importando geoai…")
    import geoai  # noqa: F401

    _emit(progress_cb, "Inicializando CLIPSegmentation para agua…")

    try:
        from geoai import CLIPSegmentation  # type: ignore[attr-defined]
    except (ImportError, AttributeError) as e:
        raise AIToolError(
            "Esta versión de geoai no expone CLIPSegmentation. "
            "Verifica que geoai-py==0.10.0 esté instalado "
            "(Pudumaps → Instalar módulo IA…)."
        ) from e

    segmenter = CLIPSegmentation()

    _emit(progress_cb, "Ejecutando segmentación de cuerpos de agua (puede descargar modelo ~600 MB la 1a vez)…")

    # CLIPSegmentation produce un raster máscara, no polígonos directamente.
    # Por eso le pedimos un archivo intermedio .tif y después vectorizamos.
    import os as _os
    mask_tif = output_path.replace(".geojson", "_water_mask.tif")
    if not mask_tif.endswith(".tif"):
        mask_tif = output_path + ".tif"

    try:
        segmenter.segment_image(
            input_path=raster_path,
            output_path=mask_tif,
            text_prompt="water bodies, lakes, rivers, reservoirs",
            threshold=0.4,  # Algo permisivo para zonas mixtas (agua + sedimento).
        )
    except TypeError:
        # Posicional por si los keywords difieren entre versiones.
        segmenter.segment_image(raster_path, mask_tif, "water bodies, lakes, rivers, reservoirs")

    if not _os.path.exists(mask_tif):
        raise AIToolError(
            "CLIPSegmentation no produjo máscara. Probablemente no se "
            "detectó agua en el área (intenta bajar el threshold o "
            "verifica que el raster tenga cuerpos de agua visibles)."
        )

    _emit(progress_cb, "Vectorizando máscara a polígonos…")
    n = _vectorize_mask_to_geojson(mask_tif, output_path)

    # Cleanup.
    try:
        _os.remove(mask_tif)
    except OSError:
        pass

    return n


def _vectorize_mask_to_geojson(mask_path: str, output_path: str) -> int:
    """Convierte un raster máscara binaria a polígonos GeoJSON.

    Returns: número de polígonos generados.
    """
    import geopandas as gpd
    import rasterio
    from rasterio.features import shapes
    from shapely.geometry import shape

    with rasterio.open(mask_path) as ds:
        mask = ds.read(1)
        transform = ds.transform
        crs = ds.crs

    # Considera "agua" cualquier pixel > 0 (CLIPSegmentation a veces
    # produce máscara binaria, a veces float 0-1 según threshold).
    polys = []
    for geom, val in shapes(mask, mask=mask > 0, transform=transform):
        polys.append({"geometry": shape(geom), "value": float(val)})

    if not polys:
        # Crear archivo vacío válido para que la UI no rompa.
        gdf = gpd.GeoDataFrame(geometry=[], crs=crs)
    else:
        gdf = gpd.GeoDataFrame(polys, crs=crs)

    gdf.to_file(output_path, driver="GeoJSON")
    return len(gdf)


__all__ = ["ExtractWaterTool"]
