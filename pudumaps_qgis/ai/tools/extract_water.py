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
    """Aísla la llamada a la API de geoai para water extraction.

    Si geoai-py cambia su API entre versiones, este es el ÚNICO lugar
    a editar. Por eso pineamos `geoai-py==0.10.0` y bumps son manuales.
    """
    _emit(progress_cb, "Importando geoai…")
    import geoai  # noqa: F401

    _emit(progress_cb, "Inicializando extractor de agua…")

    extractor = None
    try:
        # API estable 0.10.x.
        from geoai import WaterBodyExtractor  # type: ignore[attr-defined]
        extractor = WaterBodyExtractor()
    except (ImportError, AttributeError):
        pass

    if extractor is not None and hasattr(extractor, "predict"):
        _emit(progress_cb, "Ejecutando inferencia…")
        gdf = extractor.predict(raster_path)  # type: ignore[union-attr]
    else:
        # Fallback a la función de alto nivel.
        fn = getattr(geoai, "extract_water", None) or getattr(geoai, "extract_water_bodies", None)
        if fn is None:
            raise AIToolError(
                "Esta versión de geoai no expone WaterBodyExtractor ni "
                "extract_water(). Verifica que geoai-py==0.10.0 esté "
                "instalado (Pudumaps → Instalar módulo IA…)."
            )
        _emit(progress_cb, "Ejecutando inferencia…")
        gdf = fn(raster_path)

    if gdf is None:
        raise AIToolError("geoai devolvió None en lugar de un GeoDataFrame.")

    _emit(progress_cb, "Guardando GeoJSON…")
    gdf.to_file(output_path, driver="GeoJSON")

    try:
        return int(len(gdf))
    except Exception:  # noqa: BLE001
        return 0


__all__ = ["ExtractWaterTool"]
