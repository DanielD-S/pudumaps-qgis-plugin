"""Load a Pudumaps project's layers into QGIS.

Takes a `PudumapsClient` and a `project_id`. Layers with `layer_type ==
"geojson"` (uploaded/synced from QGIS) get their full geojson converted
to a memory-based QgsVectorLayer with basic default styling. Layers
added from the web app's "Capas Oficiales" catalog (`layer_type` in
wms/arcgis_map/arcgis_feature/weather) have no stored geometry — they're
live references to an external service, loaded as QgsRasterLayer/
QgsVectorLayer against that service instead (see `external_layer_to_qgis`).
Every loaded layer is tagged with its remote id as a custom property so
Fase 3+4 can detect which layers came from Pudumaps.

Audit 2026-05-07 (H3 MEDIO + H4 MEDIO): tempfile usado por OGR ahora
se borra en finally, y el GeoJSON se valida estructuralmente antes de
escribir (rechazamos shapes que no son FeatureCollection/Feature).

2026-08-17: layer_type/external_url expuestos en la API — antes toda
capa sin geojson local (wms/arcgis_map/arcgis_feature/weather) se leía
como FeatureCollection vacío y quedaba invisible sin zoom.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from typing import Any

from qgis.core import (
    QgsFillSymbol,
    QgsLineSymbol,
    QgsMapLayer,
    QgsMarkerSymbol,
    QgsProject,
    QgsRasterLayer,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .api_client import PudumapsClient, PudumapsError
from .error_utils import log_full_error, safe_error_message

# Custom properties we stamp on every layer we load so we can identify
# them later during push/sync.
PROP_LAYER_ID = "pudumaps/layer_id"
PROP_PROJECT_ID = "pudumaps/project_id"
PROP_PROJECT_NAME = "pudumaps/project_name"
PROP_LAST_HASH = "pudumaps/last_hash"
# Solo se estampa en capas externas (ver EXTERNAL_LAYER_TYPES). Su ausencia
# significa "geojson" — los callers deben leerla con ese default para no
# romper capas ya cargadas antes de este flag (sync_dialog._collect_local_layers
# la usa para excluir capas externas de push/sync: son referencias en vivo,
# no datos locales editables).
PROP_LAYER_TYPE = "pudumaps/layer_type"


@dataclass
class LoadResult:
    loaded: int
    failed: list[tuple[str, str]]  # (layer_name, error_message)
    group_name: str


class InvalidGeoJsonError(ValueError):
    """Raised when a payload doesn't look like a valid GeoJSON FeatureCollection/Feature."""


class InvalidExternalLayerError(ValueError):
    """Raised when an external-layer row is missing/malformed external_url."""


class UnsupportedLayerError(ValueError):
    """Layer type has no QGIS-loadable representation (e.g. 'weather')."""


# Capas que Pudumaps guarda como referencia a un servicio en vivo en vez de
# geojson local (ver WMSLayerPanel.persistExternalLayer en la app principal:
# geojson=null, layer_type + external_url describen la fuente real).
EXTERNAL_LAYER_TYPES = frozenset({"wms", "arcgis_map", "arcgis_feature", "weather"})


def parse_wms_external_url(external_url: str) -> tuple[str, str]:
    """Parsea el sentinel `wms://<baseUrl>?layers=<encoded>` que escribe la
    app principal (WMSLayerPanel.tsx, rehidratación ~línea 526) en
    (base_url, layers). Debe espejar esa lógica 1:1.
    """
    from urllib.parse import unquote

    without_prefix = (
        external_url[len("wms://"):] if external_url.startswith("wms://") else external_url
    )
    sep_idx = without_prefix.find("?layers=")
    if sep_idx == -1:
        raise InvalidExternalLayerError(
            f"external_url de WMS sin '?layers=': {external_url!r}"
        )
    base_url = without_prefix[:sep_idx]
    layers = unquote(without_prefix[sep_idx + len("?layers=") :])
    if not base_url or not layers:
        raise InvalidExternalLayerError(
            f"external_url de WMS con base_url o layers vacíos: {external_url!r}"
        )
    return base_url, layers


def external_layer_to_qgis(layer_type: str, external_url: str, name: str) -> QgsMapLayer:
    """Construye la capa QGIS correspondiente a una capa externa (WMS,
    ArcGIS Map/FeatureServer). `weather` no tiene representación GIS real
    (son puntos calculados en el navegador vía Open-Meteo para un set fijo
    de ciudades — no hay servicio geoespacial detrás) y siempre levanta
    UnsupportedLayerError; el caller debe reportarlo como capa no soportada,
    no como error.
    """
    if layer_type == "weather":
        raise UnsupportedLayerError(
            "Capa de clima en vivo — no soportada en el plugin QGIS (depende "
            "de Open-Meteo calculado en el navegador). Disponible solo en la "
            "web de Pudumaps."
        )
    if not external_url:
        raise InvalidExternalLayerError(f"Capa externa sin external_url: {name!r}")

    if layer_type == "wms":
        # Formato probado del connection-string wms de QGIS (PyQGIS cookbook):
        # valores planos, sin re-encodear — `layers`/`url` ya vienen
        # decodificados por parse_wms_external_url.
        base_url, layers = parse_wms_external_url(external_url)
        uri = f"crs=EPSG:4326&format=image/png&layers={layers}&styles=&url={base_url}"
        return QgsRasterLayer(uri, name, "wms")

    if layer_type == "arcgis_map":
        # Proveedores ESRI de QGIS parsean un connection-string key=value
        # (igual que wms) — la URL pelada sin el prefijo `url=` "funciona"
        # (isValid()==True, el provider se instancia) pero no encuentra el
        # servicio real: 0 features/tiles sin error visible. Confirmado en
        # producción (2026-08-17): la URL sola dejaba la capa vacía aunque
        # el servicio respondía bien por curl.
        return QgsRasterLayer(f"url={external_url}", name, "arcgismapserver")

    if layer_type == "arcgis_feature":
        return QgsVectorLayer(f"url={external_url}", name, "arcgisfeatureserver")

    raise UnsupportedLayerError(f"Tipo de capa desconocido: {layer_type!r}")


def validate_geojson_shape(geojson: Any) -> None:
    """Audit H4: chequeo defensivo del shape antes de pasar a OGR.

    No es validación geométrica completa (RFC 7946) — solo descarta
    payloads claramente no-GeoJSON que crashearían OGR de formas opacas
    o causarían recursión profunda. La validación geométrica fina vive
    en el backend (validateGeoJson.ts).
    """
    if not isinstance(geojson, dict):
        raise InvalidGeoJsonError("GeoJSON debe ser un objeto JSON.")
    t = geojson.get("type")
    if t == "FeatureCollection":
        features = geojson.get("features")
        if features is not None and not isinstance(features, list):
            raise InvalidGeoJsonError(
                "FeatureCollection.features debe ser una lista."
            )
    elif t == "Feature":
        if not isinstance(geojson.get("geometry"), (dict, type(None))):
            raise InvalidGeoJsonError(
                "Feature.geometry debe ser un objeto o null."
            )
    else:
        raise InvalidGeoJsonError(
            f"Tipo GeoJSON no soportado: {t!r}. "
            "Esperado: FeatureCollection o Feature."
        )


def infer_geometry_type(geojson: dict[str, Any]) -> str:
    """Return a QGIS memory-layer URI geometry type from a GeoJSON object.

    Falls back to "MultiPolygon" for empty FeatureCollections (most permissive).
    """
    if geojson.get("type") == "Feature":
        features = [geojson]
    else:
        features = geojson.get("features") or []

    for f in features:
        g = (f or {}).get("geometry") or {}
        t = g.get("type")
        if t in {
            "Point",
            "MultiPoint",
            "LineString",
            "MultiLineString",
            "Polygon",
            "MultiPolygon",
        }:
            return t

    # Empty or unusable — MultiPolygon is the most permissive fallback
    # (a memory layer still renders, and users can later add features).
    return "MultiPolygon"


def apply_default_style(layer: QgsVectorLayer) -> None:
    """Apply a basic Pudumaps-green style so loaded layers are immediately
    visible. Users can customize afterwards — QGIS persists it in the
    project file.
    """
    geom = layer.geometryType()
    # QgsWkbTypes: 0=point, 1=line, 2=polygon, 3=unknown, 4=null
    if geom == 0:  # point
        symbol = QgsMarkerSymbol.createSimple(
            {"color": "#22c55e", "outline_color": "#166534", "size": "3"}
        )
    elif geom == 1:  # line
        symbol = QgsLineSymbol.createSimple(
            {"color": "#22c55e", "width": "0.6"}
        )
    elif geom == 2:  # polygon
        symbol = QgsFillSymbol.createSimple(
            {
                "color": "60,197,128,80",  # rgba — 30% alpha
                "outline_color": "#16a34a",
                "outline_width": "0.5",
            }
        )
    else:
        return
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))


def geojson_to_layer(
    geojson: dict[str, Any],
    name: str,
    *,
    remote_layer_id: str = "",
    remote_project_id: str = "",
    remote_project_name: str = "",
) -> QgsVectorLayer:
    """Convert a GeoJSON dict into a QgsVectorLayer (memory provider).

    Uses OGR via a temp file because it handles every GeoJSON edge case
    (mixed types, null geometries already filtered, CRS detection via
    `crs` member, etc.) while QgsJsonUtils has subtle schema-inference
    limitations.

    Audit H3 (2026-05-07): el tempfile se borra en finally aunque OGR
    falle. Si el fallback necesita mantener el archivo en disco para la
    sesión (caso `layer = ogr_layer`), lo registramos en la layer para
    que QGIS lo limpie al cerrar el proyecto.
    """
    validate_geojson_shape(geojson)
    geom_type = infer_geometry_type(geojson)

    tmp_path: str | None = None
    keep_tmp_for_layer = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".geojson", delete=False, encoding="utf-8"
        ) as tmp:
            json.dump(geojson, tmp)
            tmp_path = tmp.name

        ogr_layer = QgsVectorLayer(tmp_path, name, "ogr")
        if not ogr_layer.isValid() or ogr_layer.featureCount() == 0:
            # Fallback: empty memory layer with best-guess geometry. User can
            # still push edits back and the layer will populate on next pull.
            uri = f"{geom_type}?crs=EPSG:4326"
            layer = QgsVectorLayer(uri, name, "memory")
        else:
            # Copy features from OGR layer into an in-memory layer so we own
            # its lifecycle (and can later dirty-track / sync).
            #
            # Use OGR's actual wkbType (not our inferred geom_type) because
            # OGR promotes single geometries to their Multi- variant when
            # loading GeoJSON, and a memory layer created as "Polygon" will
            # silently reject MultiPolygon features on addFeatures().
            wkb_type = ogr_layer.wkbType()
            geom_name = QgsWkbTypes.displayString(wkb_type) or geom_type
            crs_authid = ogr_layer.crs().authid() or "EPSG:4326"
            uri = f"{geom_name}?crs={crs_authid}"
            fields_uri_parts = [
                f"field={_safe_field_name(f.name())}:{_field_type_for(f.type())}"
                for f in ogr_layer.fields()
            ]
            if fields_uri_parts:
                uri += "&" + "&".join(fields_uri_parts)
            layer = QgsVectorLayer(uri, name, "memory")
            if not layer.isValid():
                # Memory provider rejected the URI — last resort, use OGR layer
                # directly. El tempfile DEBE sobrevivir para que OGR lo lea.
                layer = ogr_layer
                keep_tmp_for_layer = True
            else:
                pr = layer.dataProvider()
                ok, _added = pr.addFeatures(list(ogr_layer.getFeatures()))
                if not ok or layer.featureCount() == 0:
                    # addFeatures rejected silently — fall back to OGR layer.
                    layer = ogr_layer
                    keep_tmp_for_layer = True
                else:
                    layer.updateExtents()

        # Stamp remote metadata on the layer for future push/sync
        if remote_layer_id:
            layer.setCustomProperty(PROP_LAYER_ID, remote_layer_id)
        if remote_project_id:
            layer.setCustomProperty(PROP_PROJECT_ID, remote_project_id)
        if remote_project_name:
            layer.setCustomProperty(PROP_PROJECT_NAME, remote_project_name)

        apply_default_style(layer)
        if keep_tmp_for_layer and tmp_path:
            # Marca para limpieza por si el caller quiere borrarlo después.
            # NO lo borramos aquí porque OGR lo está leyendo on-demand.
            layer.setCustomProperty("pudumaps/_tmp_geojson_path", tmp_path)
        return layer
    finally:
        # H3: borrar tempfile siempre que NO lo necesite la layer OGR-backed.
        if tmp_path and not keep_tmp_for_layer:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass  # ya borrado o permiso denegado — no es crítico


def load_project(
    client: PudumapsClient,
    project_id: str,
    project_name: str,
    *,
    progress_cb=None,
) -> LoadResult:
    """Pull all layers of a Pudumaps project into the active QGIS project.

    If a layer with matching `pudumaps/layer_id` already exists in the
    project, it is reused (features replaced) instead of creating a
    duplicate. This avoids two-layers-pointing-to-one-remote when the
    user has just pushed a layer and then opens the same project.

    `progress_cb(done, total, current_name)` is called before each layer
    fetch. Exceptions per-layer are caught so one bad layer doesn't abort
    the whole import.
    """
    import hashlib
    import json as _json

    summaries = client.list_layers(project_id)
    total = len(summaries)
    project = QgsProject.instance()
    group_name = f"Pudumaps: {project_name}"
    root = project.layerTreeRoot()

    existing_group = root.findGroup(group_name)
    group = existing_group or root.insertGroup(0, group_name)

    # Build a lookup of already-present layers by remote id so we can
    # dedupe (Fase 4 safeguard). Cualquier tipo de capa cuenta — las capas
    # externas (wms/arcgis_map) son QgsRasterLayer, no QgsVectorLayer.
    existing_by_remote_id: dict[str, QgsMapLayer] = {}
    for layer in project.mapLayers().values():
        rid = layer.customProperty(PROP_LAYER_ID, "")
        if rid:
            existing_by_remote_id[rid] = layer

    loaded = 0
    failed: list[tuple[str, str]] = []

    for idx, summary in enumerate(summaries):
        if progress_cb:
            progress_cb(idx, total, summary.name)
        try:
            full = client.get_layer(summary.id)
            layer_type = full.get("layer_type") or "geojson"

            if layer_type in EXTERNAL_LAYER_TYPES:
                # Capa externa (wms/arcgis_map/arcgis_feature/weather):
                # geojson viene null a propósito — no hay features locales,
                # es una referencia a un servicio en vivo (o, para 'weather',
                # algo que el plugin no puede representar).
                if summary.id in existing_by_remote_id:
                    # Ya está cargada. No hay features locales que refrescar
                    # (el servicio se re-consulta en vivo cada vez que QGIS
                    # dibuja el canvas), así que no recreamos la capa.
                    loaded += 1
                    continue

                ext_layer = external_layer_to_qgis(
                    layer_type, full.get("external_url") or "", name=summary.name
                )
                if not ext_layer.isValid():
                    failed.append(
                        (
                            summary.name,
                            f"external_layer_invalid: no se pudo cargar "
                            f"{layer_type} desde {full.get('external_url')!r}",
                        )
                    )
                    continue

                ext_layer.setCustomProperty(PROP_LAYER_ID, summary.id)
                ext_layer.setCustomProperty(PROP_PROJECT_ID, project_id)
                ext_layer.setCustomProperty(PROP_PROJECT_NAME, project_name)
                ext_layer.setCustomProperty(PROP_LAYER_TYPE, layer_type)
                project.addMapLayer(ext_layer, addToLegend=False)
                group.addLayer(ext_layer)
                loaded += 1
                continue

            geojson = full.get("geojson") or {"type": "FeatureCollection", "features": []}

            # Compute the canonical hash once and reuse
            hash_ = hashlib.sha256(
                _json.dumps(geojson, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()

            existing = existing_by_remote_id.get(summary.id)
            if existing is not None:
                # Refresh the existing layer's features in-place and
                # re-stamp hashes; no new duplicate layer.
                from .sync_manager import stamp_hash  # lazy to avoid cycle
                _replace_features(existing, geojson)
                stamp_hash(existing, hash_)
                loaded += 1
                continue

            layer = geojson_to_layer(
                geojson,
                name=summary.name,
                remote_layer_id=summary.id,
                remote_project_id=project_id,
                remote_project_name=project_name,
            )
            layer.setCustomProperty(PROP_LAST_HASH, hash_)
            project.addMapLayer(layer, addToLegend=False)
            group.addLayer(layer)
            loaded += 1
        except PudumapsError as e:
            failed.append(
                (summary.name, f"{e.code or 'api_error'}: {safe_error_message(e)}")
            )
        except UnsupportedLayerError as e:
            # Conocido y esperado (ej. 'weather') — no es un bug, no se
            # loguea como tal.
            failed.append((summary.name, str(e)))
        except Exception as e:  # noqa: BLE001
            log_full_error("project_loader.load_project", e)
            failed.append((summary.name, f"unexpected: {safe_error_message(e)}"))

    if progress_cb:
        progress_cb(total, total, "")

    _zoom_to_group(group)

    return LoadResult(loaded=loaded, failed=failed, group_name=group_name)


def _zoom_to_group(group) -> None:
    """Compute combined extent of all layers in the group and zoom the
    active map canvas to it. Best-effort — failures are swallowed."""
    try:
        from qgis.core import QgsRectangle
        from qgis.utils import iface  # type: ignore

        combined: QgsRectangle | None = None
        for child in group.findLayers():
            layer = child.layer()
            if layer is None or not layer.isValid():
                continue
            # featureCount() solo existe en capas vectoriales — las capas
            # externas (wms/arcgis_map) son QgsRasterLayer y no lo tienen.
            # Sin este guard, la primera capa raster del grupo tira una
            # excepción que aborta el cálculo de extent para TODO el grupo
            # (el try/except de más abajo la traga silenciosamente).
            if isinstance(layer, QgsVectorLayer) and layer.featureCount() == 0:
                continue
            extent = layer.extent()
            if extent.isNull() or extent.isEmpty():
                continue
            if combined is None:
                combined = QgsRectangle(extent)
            else:
                combined.combineExtentWith(extent)

        if combined is not None and iface is not None:
            canvas = iface.mapCanvas()
            # Small buffer so features don't touch the edges
            combined.scale(1.1)
            canvas.setExtent(combined)
            canvas.refresh()
    except Exception:  # noqa: BLE001
        pass


# ── Helpers ──────────────────────────────────────────────────────────────


def _safe_field_name(name: str) -> str:
    """QGIS memory provider needs simple field names without special chars."""
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in (name or ""))
    return safe or "field"


def _replace_features(layer: QgsVectorLayer, geojson: dict[str, Any]) -> None:
    """Replace all features of an existing memory-backed layer with
    features from a fresh GeoJSON. Used by pull's dedup path."""
    src = geojson_to_layer(geojson, name="__dedup_tmp__")
    pr = layer.dataProvider()
    ids = [f.id() for f in layer.getFeatures()]
    if ids:
        pr.deleteFeatures(ids)
    pr.addFeatures(list(src.getFeatures()))
    layer.updateExtents()
    layer.triggerRepaint()


def _field_type_for(qvariant_type: int) -> str:
    # Qt QVariant type → QGIS memory URI field type
    # 2=Int, 6=Double, 4=LongLong, 10=String, 14=Date, 16=DateTime
    mapping = {
        2: "integer",
        4: "integer64",
        6: "double",
        10: "string",
        14: "date",
        16: "datetime",
    }
    return mapping.get(qvariant_type, "string")
