"""Clasificación de uso de suelo sobre raster RGB usando geoai.

Wrapper del clasificador de landcover de geoai-py. Toma un raster RGB
y produce un raster categórico (GeoTIFF) donde cada píxel tiene un
índice de clase (built / forest / water / cropland / shrubland / bare).

Sidecar JSON con el mapeo `índice → nombre_clase_en_español`,
re-etiquetado según la ecorregión chilena del bbox (Nivel 1
chilenización). Ver `chile_classes.translate_class`.

Caveats Chile (ver docs/modelos-chile.md):
- Funciona bien para clases gruesas (urbano, agua, agricultura) en
  zona central con orto o Sentinel-2.
- No distingue bosque nativo de plantación forestal — los modelos
  USA tratan ambos como "forest". Para esa distinción esperar v0.8
  con `pudumaps/bosque-nativo-cl-v1`.
- En zonas áridas (Atacama, Norte chico) confunde "bare" con "built"
  cuando hay caminos polvorientos visibles. Revisar manualmente.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

from ..chile_classes import ecoregion_for_bbox, ecoregion_name, translate_class
from .base import AITool, AIToolError, ProgressCallback


class LandCoverClassificationTool(AITool):
    id = "landcover_classification"
    name = "Clasificar uso de suelo [experimental]"
    description = (
        "Clasifica cada píxel del raster RGB en categorías de uso de suelo. "
        "EXPERIMENTAL: el modelo default de geoai es Mask2Former entrenado "
        "para escenas urbanas (cityscapes), NO para imagen satelital de "
        "landcover. Resultados pueden ser raros sobre Sentinel-2. "
        "Mejora planeada para v0.8 con modelo HF específico de landcover."
    )
    requires = ["geoai"]
    input_kind = "raster"
    output_suffix = ".tif"

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
        """Genera un GeoTIFF categórico + sidecar JSON con leyenda.

        `output_path` debe terminar en .tif/.tiff. Se crea también un
        archivo hermano `<output>.classes.json` con el mapeo de índices
        a etiquetas en español (re-etiquetadas por ecorregión si el
        bbox cae en Chile).
        """
        self.ensure_available()
        _emit(progress_cb, "Cargando módulo geoai…")

        if not os.path.exists(raster_path):
            raise AIToolError(f"No existe el raster: {raster_path}")

        out_dir = os.path.dirname(os.path.abspath(output_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        try:
            class_map, bbox = _run_geoai_landcover(
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

        # Re-etiquetar al vocabulario chileno (Nivel 1) y persistir leyenda.
        sidecar = _build_legend_sidecar(class_map, bbox)
        legend_path = output_path + ".classes.json"
        try:
            with open(legend_path, "w", encoding="utf-8") as f:
                json.dump(sidecar, f, ensure_ascii=False, indent=2)
        except OSError:
            # No fatal — el raster ya está escrito. Dejamos log al panel.
            _emit(progress_cb, "Aviso: no se pudo guardar la leyenda JSON.")

        _emit(progress_cb, f"Listo: {len(class_map)} clases detectadas.")
        return output_path


def _emit(cb: Optional[ProgressCallback], msg: str) -> None:
    if cb is None:
        return
    try:
        cb(msg)
    except Exception:  # noqa: BLE001
        pass


def _run_geoai_landcover(
    raster_path: str,
    output_path: str,
    progress_cb: Optional[ProgressCallback],
) -> Tuple[List[str], Optional[Tuple[float, float, float, float]]]:
    """Llamada real a la API de geoai 0.10.x.

    geoai 0.10 NO tiene `LandCoverClassifier`. Lo más cercano es la
    función `image_segmentation()` en `geoai.hf` que usa modelos HF de
    segmentación semántica genérica. Por defecto baja
    `facebook/mask2former-swin-large-cityscapes-semantic` que está
    entrenado para escenas URBANAS (calles, autos, peatones, edificios)
    — NO para landcover satelital.

    Sobre ortofoto urbana de Santiago el resultado es razonable; sobre
    Sentinel-2 dará clases extrañas. Esta tool queda como experimental
    hasta v0.8 donde montaremos un modelo HF específico de landcover
    (ej. Prithvi de NASA/IBM).

    Returns:
        (class_names_en_orden, bbox_en_4326_o_None)
    """
    _emit(progress_cb, "Importando geoai…")
    import geoai  # noqa: F401

    _emit(progress_cb, "Inicializando segmentador HF (modelo se descarga ~1.5 GB la 1a vez)…")

    # geoai.image_segmentation está exportado desde geoai/hf.py.
    # Firma típica: image_segmentation(tif_path, output_path, ...).
    fn = getattr(geoai, "image_segmentation", None)
    if fn is None:
        raise AIToolError(
            "Esta versión de geoai no expone image_segmentation(). "
            "Verifica que geoai-py==0.10.0 esté instalado "
            "(Pudumaps → Instalar módulo IA…)."
        )

    _emit(progress_cb, "Ejecutando segmentación semántica…")
    try:
        result = fn(tif_path=raster_path, output_path=output_path)
    except TypeError:
        # Algunas versiones usan kwargs distintos. Probar posicional.
        result = fn(raster_path, output_path)

    # La función devuelve (output_path, label_mapping, scores). Aceptamos
    # cualquier shape razonable y extraemos las clases.
    class_names = _extract_class_names_from_result(result)
    bbox = _extract_bbox_from_raster(raster_path)
    return class_names, bbox


def _extract_class_names_from_result(result) -> List[str]:
    """Acepta tuple, dict, o list y devuelve lista de nombres de clase."""
    if result is None:
        return _default_landcover_classes()

    # tuple (path, mapping, scores)?
    if isinstance(result, tuple):
        for item in result:
            if isinstance(item, dict) and item:
                # Mapping idx→name o name→idx.
                values = list(item.values())
                if all(isinstance(v, str) for v in values):
                    return values
                keys = list(item.keys())
                if all(isinstance(k, str) for k in keys):
                    return keys
            if isinstance(item, (list, tuple)) and item and isinstance(item[0], str):
                return list(item)
        # No encontramos nombres claros — fallback.
        return _default_landcover_classes()

    if isinstance(result, dict):
        values = list(result.values())
        if values and all(isinstance(v, str) for v in values):
            return values

    if isinstance(result, (list, tuple)) and result and isinstance(result[0], str):
        return list(result)

    return _default_landcover_classes()


def _default_landcover_classes() -> List[str]:
    """Nombres genéricos cuando no podemos extraerlos del resultado."""
    return ["built", "agriculture", "forest", "shrubland", "grassland", "water", "bare"]


def _extract_bbox_from_raster(
    raster_path: str,
) -> Optional[Tuple[float, float, float, float]]:
    """Lee bbox en EPSG:4326 del raster usando rasterio si está disponible.

    Si rasterio no está (o el raster tiene CRS exótico), devuelve None y
    el re-etiquetado cae al modo genérico (sin ecorregión).
    """
    try:
        import rasterio  # noqa: WPS433
        from rasterio.warp import transform_bounds  # noqa: WPS433
    except ImportError:
        return None

    try:
        with rasterio.open(raster_path) as ds:
            left, bottom, right, top = ds.bounds
            if ds.crs is None:
                return None
            if ds.crs.to_epsg() == 4326:
                return (left, bottom, right, top)
            left4, bottom4, right4, top4 = transform_bounds(
                ds.crs, "EPSG:4326", left, bottom, right, top, densify_pts=21
            )
            return (left4, bottom4, right4, top4)
    except Exception:  # noqa: BLE001
        return None


def _build_legend_sidecar(
    class_names: List[str],
    bbox: Optional[Tuple[float, float, float, float]],
) -> Dict:
    """Construye el dict JSON con leyenda re-etiquetada en español + Chile."""
    eco_key = ecoregion_for_bbox(bbox)
    legend = []
    for idx, name in enumerate(class_names):
        legend.append(
            {
                "index": idx,
                "original": name,
                "es": translate_class(name, bbox=bbox),
            }
        )
    return {
        "tool": "landcover_classification",
        "bbox_4326": list(bbox) if bbox else None,
        "ecoregion": {"key": eco_key, "name": ecoregion_name(eco_key)},
        "classes": legend,
    }


__all__ = ["LandCoverClassificationTool"]
