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

    geoai.BuildingFootprintExtractor.process_raster() es la pipeline
    completa: tile → infer → vectorize → escribe GeoJSON. Devuelve un
    GeoDataFrame Y escribe a `output_path` si se provee.

    El método acepta kwargs útiles:
    - confidence_threshold (default 0.5): min score para retener detección
    - chip_size (default 512): tamaño del tile de inferencia
    - min_object_area: filtro de área mínima en pixels
    - filter_edges (default True): descarta detecciones tocando el borde
    - regularize (interno): ortogonaliza polígonos detectados

    Si la API cambia entre versiones del paquete, este helper es el
    único lugar a tocar.

    Returns:
        Número de edificaciones detectadas.
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

    import os as _os

    _emit(progress_cb, "Ejecutando inferencia sobre raster (puede tardar varios minutos)…")
    # process_raster() hace toda la pipeline: tile, infer, vectorize, escribir.
    # Devuelve un GeoDataFrame. Si output_path se pasa, también escribe a disco.
    try:
        gdf = extractor.process_raster(
            raster_path=raster_path,
            output_path=output_path,
        )
    except TypeError:
        # Fallback posicional si el orden de kwargs cambia entre versiones.
        gdf = extractor.process_raster(raster_path, output_path)

    # Algunas versiones devuelven None aunque escriban a disco — chequeamos
    # ambos casos.
    if gdf is None and not _os.path.exists(output_path):
        raise AIToolError(
            "geoai no produjo output. Probablemente no se detectaron "
            "edificios en el área, o el modelo rinde mal sobre este "
            "tipo de imagen (ver docs/modelos-chile.md). Para Sentinel-2 "
            "10m/px solo se detectan edificios grandes; mejor usar "
            "ortofoto ≤1m/px."
        )

    # Si gdf es válido pero el archivo no se escribió, lo escribimos a mano.
    if gdf is not None and not _os.path.exists(output_path):
        gdf.to_file(output_path, driver="GeoJSON")

    # Si el archivo existe pero gdf es None, lo leemos para contar features.
    if gdf is None:
        try:
            import geopandas as gpd
            gdf = gpd.read_file(output_path)
        except Exception:  # noqa: BLE001
            return 0

    try:
        n = int(len(gdf))
    except Exception:  # noqa: BLE001
        n = 0

    if n == 0:
        # Edge case: el método corrió OK pero no detectó nada. Avisar al
        # usuario explícitamente en vez de mostrar capa vacía.
        raise AIToolError(
            "No se detectaron edificios en el raster. Posibles causas:\n"
            "- Imagen Sentinel a 10m/px: solo detecta edificios grandes "
            "(>200 m²). Prueba ortofoto IDE Chile.\n"
            "- Área no urbana o muy nublada.\n"
            "- Modelo (USA) rinde mal en zonas rurales chilenas."
        )

    _emit(progress_cb, f"Detectados {n} edificios.")
    return n


__all__ = ["ExtractBuildingsTool"]
