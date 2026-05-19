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
    name = "Clasificar uso de suelo"
    description = (
        "Clasifica cada píxel del raster RGB en categorías de uso de suelo "
        "(urbano, agua, bosque, cultivos, matorral, suelo desnudo). "
        "Las clases se traducen al español + ecorregión chilena cuando aplica."
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
    """Aísla la llamada a la API de geoai para landcover.

    Returns:
        (class_names_en_orden, bbox_en_4326_o_None)
    """
    _emit(progress_cb, "Importando geoai…")
    import geoai  # noqa: F401

    _emit(progress_cb, "Inicializando clasificador de uso de suelo…")

    classifier = None
    try:
        from geoai import LandCoverClassifier  # type: ignore[attr-defined]
        classifier = LandCoverClassifier()
    except (ImportError, AttributeError):
        pass

    if classifier is not None and hasattr(classifier, "predict"):
        _emit(progress_cb, "Ejecutando inferencia…")
        result = classifier.predict(raster_path, output_path=output_path)
    else:
        fn = (
            getattr(geoai, "classify_landcover", None)
            or getattr(geoai, "predict_landcover", None)
        )
        if fn is None:
            raise AIToolError(
                "Esta versión de geoai no expone LandCoverClassifier ni "
                "classify_landcover(). Verifica que geoai-py==0.10.0 "
                "esté instalado (Pudumaps → Instalar módulo IA…)."
            )
        _emit(progress_cb, "Ejecutando inferencia…")
        result = fn(raster_path, output_path=output_path)

    if result is None:
        raise AIToolError("geoai devolvió None en lugar de un resultado.")

    # Nombres de clase: distintas versiones de geoai los exponen distinto.
    class_names = _extract_class_names(result, classifier)
    bbox = _extract_bbox_from_raster(raster_path)
    return class_names, bbox


def _extract_class_names(result, classifier) -> List[str]:
    """Extrae lista de nombres de clase del objeto que devuelve geoai.

    Heurística: revisa atributos comunes (`class_names`, `classes`,
    `labels`) tanto en el resultado como en el classifier. Si nada
    funciona, devuelve nombres genéricos.
    """
    for src in (result, classifier):
        if src is None:
            continue
        for attr in ("class_names", "classes", "labels"):
            value = getattr(src, attr, None)
            if isinstance(value, (list, tuple)) and value:
                return [str(v) for v in value]
            if isinstance(value, dict) and value:
                # dict idx→nombre: ordenar por idx.
                try:
                    items = sorted(value.items(), key=lambda kv: int(kv[0]))
                    return [str(v) for _k, v in items]
                except (TypeError, ValueError):
                    pass
    # Fallback: nombres genéricos comunes en modelos de landcover.
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
