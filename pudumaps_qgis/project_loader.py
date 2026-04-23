"""Load a Pudumaps project's layers into QGIS as QgsVectorLayers.

Takes a `PudumapsClient` and a `project_id`. Fetches each layer's full
geojson and converts it to a memory-based QgsVectorLayer. Applies basic
default styling and tags the layer with its remote id as a custom
property so Fase 3+4 can detect which layers came from Pudumaps.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from typing import Any

from qgis.core import (
    QgsFillSymbol,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsProject,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .api_client import PudumapsClient, PudumapsError

# Custom properties we stamp on every layer we load so we can identify
# them later during push/sync.
PROP_LAYER_ID = "pudumaps/layer_id"
PROP_PROJECT_ID = "pudumaps/project_id"
PROP_PROJECT_NAME = "pudumaps/project_name"
PROP_LAST_HASH = "pudumaps/last_hash"


@dataclass
class LoadResult:
    loaded: int
    failed: list[tuple[str, str]]  # (layer_name, error_message)
    group_name: str


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
    """
    geom_type = infer_geometry_type(geojson)

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
            # directly. The tempfile stays on disk for the QGIS session.
            layer = ogr_layer
        else:
            pr = layer.dataProvider()
            ok, _added = pr.addFeatures(list(ogr_layer.getFeatures()))
            if not ok or layer.featureCount() == 0:
                # addFeatures rejected silently — fall back to OGR layer.
                layer = ogr_layer
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
    return layer


def load_project(
    client: PudumapsClient,
    project_id: str,
    project_name: str,
    *,
    progress_cb=None,
) -> LoadResult:
    """Pull all layers of a Pudumaps project into the active QGIS project.

    `progress_cb(done, total, current_name)` is called before each layer
    fetch. Exceptions per-layer are caught so one bad layer doesn't abort
    the whole import.
    """
    summaries = client.list_layers(project_id)
    total = len(summaries)
    project = QgsProject.instance()
    group_name = f"Pudumaps: {project_name}"
    root = project.layerTreeRoot()

    # Reuse an existing group with the same name, or create a new one
    existing_group = root.findGroup(group_name)
    group = existing_group or root.insertGroup(0, group_name)

    loaded = 0
    failed: list[tuple[str, str]] = []

    for idx, summary in enumerate(summaries):
        if progress_cb:
            progress_cb(idx, total, summary.name)
        try:
            full = client.get_layer(summary.id)
            geojson = full.get("geojson") or {"type": "FeatureCollection", "features": []}
            layer = geojson_to_layer(
                geojson,
                name=summary.name,
                remote_layer_id=summary.id,
                remote_project_id=project_id,
                remote_project_name=project_name,
            )
            project.addMapLayer(layer, addToLegend=False)
            group.addLayer(layer)
            loaded += 1
        except PudumapsError as e:
            failed.append((summary.name, f"{e.code or 'api_error'}: {e}"))
        except Exception as e:  # noqa: BLE001
            failed.append((summary.name, f"unexpected: {e}"))

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
            if layer.featureCount() == 0:
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
