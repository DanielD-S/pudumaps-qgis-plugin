"""Detección de edificaciones sobre raster RGB usando geoai.

Wrapper del modelo de building-footprint extraction de geoai-py. Toma
un raster con tres bandas (R,G,B) o NAIP-style 4-band (R,G,B,NIR) y
produce polígonos GeoJSON con las edificaciones detectadas.

Notas Chile (Nivel 1 chilenización):
- Los pesos pre-entrenados de geoai vienen sesgados a NAIP/EE.UU. — el
  modelo rinde bien en zonas urbanas tipo Las Condes/Providencia con
  ortofoto del IGM, pero falla en casas rurales de adobe, palafitos
  Chiloé y mediaguas. Documentado en `docs/modelos-chile.md` (TBD).
- Para imagen satelital chilena cruda (Sentinel/Planet), el modelo
  detecta solo los edificios grandes (>200 m²). Para precisión fina
  habrá que finetunear (planeado v0.8 — Nivel 2).
"""

from __future__ import annotations

import os
from typing import Dict, Optional

from .base import AITool, AIToolError, ProgressCallback


class ExtractBuildingsTool(AITool):
    id = "extract_buildings"
    name = "Detectar edificaciones"
    description = (
        "Segmenta edificios sobre un raster RGB y produce polígonos. "
        "Funciona mejor sobre ortofoto urbana de alta resolución (≤1 m/px). "
        "Para imagen satelital de baja resolución detecta solo edificios grandes."
    )
    requires = ["geoai"]
    input_kind = "raster"

    # ── Validación de input ─────────────────────────────────────────

    def validate_input(self, layer) -> Optional[str]:
        """Acepta solo `QgsRasterLayer` con ≥3 bandas.

        Diseñado para tolerar `layer is None` (caso: no hay capa activa).
        """
        if layer is None:
            return "Selecciona primero una capa raster en QGIS."

        # Duck-typing — preferimos no importar QgsRasterLayer aquí para
        # mantener el módulo importable sin QGIS (tests).
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
        """Corre la segmentación. Bloquea; correr desde un QgsTask.

        Args:
            raster_path: GeoTIFF / VRT / cualquier formato GDAL leíble.
            output_path: destino GeoJSON (.geojson). Si existe, se sobreescribe.
            params: ignorado por ahora (espacio para tile_size, threshold...).
            progress_cb: callback `(msg) -> None`.

        Returns:
            output_path (mismo que entra).
        """
        self.ensure_available()
        _emit(progress_cb, "Cargando módulo geoai (puede tardar la primera vez)…")

        if not os.path.exists(raster_path):
            raise AIToolError(f"No existe el raster: {raster_path}")

        # Crear directorio destino si no existe.
        out_dir = os.path.dirname(os.path.abspath(output_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        try:
            polygons = _run_geoai_buildings(
                raster_path=raster_path,
                output_path=output_path,
                progress_cb=progress_cb,
            )
        except AIToolError:
            raise
        except Exception as e:  # noqa: BLE001
            # Cualquier ruptura de la API de geoai cae aquí — preservamos
            # el detalle en el mensaje para que el panel lo loggee.
            raise AIToolError(
                f"Falla al ejecutar geoai: {type(e).__name__}: {e}"
            ) from e

        _emit(progress_cb, f"Listo: {polygons} edificaciones detectadas.")
        return output_path


def _emit(cb: Optional[ProgressCallback], msg: str) -> None:
    """Helper para llamar al progress_cb sin trampear errores del cb."""
    if cb is None:
        return
    try:
        cb(msg)
    except Exception:  # noqa: BLE001
        pass


def _run_geoai_buildings(
    raster_path: str,
    output_path: str,
    progress_cb: Optional[ProgressCallback],
) -> int:
    """Llamada a la API real de geoai 0.10.x.

    geoai.BuildingFootprintExtractor extiende ObjectDetector. El método
    principal es `process_raster(raster_path, output_path=...)` (NO
    `predict()`). Salida: GeoTIFF con máscaras + GeoJSON con polígonos.

    Si la API cambia entre versiones del paquete, este helper es el
    único lugar a tocar. Por eso pineamos versión exacta en
    `pudumaps_qgis/ai/__init__.py`.

    Returns:
        Número de edificaciones detectadas (best-effort).
    """
    _emit(progress_cb, "Importando geoai…")
    import geoai  # noqa: F401  (chequea que el módulo carga)

    _emit(progress_cb, "Inicializando extractor de edificios…")

    try:
        from geoai import BuildingFootprintExtractor  # type: ignore[attr-defined]
    except (ImportError, AttributeError) as e:
        raise AIToolError(
            "Esta versión de geoai no expone BuildingFootprintExtractor. "
            "Verifica que geoai-py==0.10.0 esté instalado "
            "(Pudumaps → Instalar módulo IA…)."
        ) from e

    extractor = BuildingFootprintExtractor()

    # process_raster() puede escribir directamente al output (GeoTIFF
    # con máscara). Pero queremos vectorial — así que pedimos un GeoTIFF
    # intermedio y después llamamos masks_to_vector().
    import os as _os
    masks_geotiff = output_path.replace(".geojson", "_masks.tif")
    if not masks_geotiff.endswith(".tif"):
        masks_geotiff = output_path + ".tif"

    _emit(progress_cb, "Ejecutando inferencia sobre raster (puede tardar varios minutos)…")
    try:
        extractor.process_raster(
            raster_path,
            output_path=masks_geotiff,
        )
    except TypeError:
        # Algunas versiones no aceptan output_path como kwarg; intentar posicional.
        extractor.process_raster(raster_path, masks_geotiff)

    if not _os.path.exists(masks_geotiff):
        raise AIToolError(
            "geoai no produjo el archivo de máscaras esperado. "
            "Probablemente no se detectaron edificios en el área, o el modelo "
            "rinde mal sobre este tipo de imagen (ver docs/modelos-chile.md)."
        )

    _emit(progress_cb, "Vectorizando máscaras a polígonos…")
    if hasattr(extractor, "masks_to_vector"):
        gdf = extractor.masks_to_vector(masks_geotiff, output_path=output_path)
    elif hasattr(extractor, "vectorize_masks"):
        gdf = extractor.vectorize_masks(masks_geotiff, output_path=output_path)
    else:
        # Último recurso: usar rasterio + shapely para vectorizar manualmente.
        gdf = _vectorize_with_rasterio(masks_geotiff, output_path, progress_cb)

    # Si la API no escribió el GeoJSON pero devolvió un GeoDataFrame, lo escribimos.
    if not _os.path.exists(output_path):
        if gdf is None:
            raise AIToolError("Vectorización no produjo salida.")
        gdf.to_file(output_path, driver="GeoJSON")

    # Cleanup del raster intermedio.
    try:
        _os.remove(masks_geotiff)
    except OSError:
        pass

    try:
        return int(len(gdf)) if gdf is not None else 0
    except Exception:  # noqa: BLE001
        return 0


def _vectorize_with_rasterio(
    raster_path: str,
    output_path: str,
    progress_cb: Optional[ProgressCallback],
):
    """Fallback puro python para vectorizar una máscara raster.

    Solo se usa si geoai.BuildingFootprintExtractor no expone
    masks_to_vector ni vectorize_masks (improbable, pero defensivo).
    """
    _emit(progress_cb, "Fallback: vectorizando con rasterio…")
    import geopandas as gpd
    import rasterio
    from rasterio.features import shapes
    from shapely.geometry import shape

    with rasterio.open(raster_path) as ds:
        mask = ds.read(1)
        transform = ds.transform
        crs = ds.crs

    polys = []
    for geom, val in shapes(mask, mask=mask > 0, transform=transform):
        polys.append(shape(geom))

    gdf = gpd.GeoDataFrame(geometry=polys, crs=crs)
    gdf.to_file(output_path, driver="GeoJSON")
    return gdf


__all__ = ["ExtractBuildingsTool"]
