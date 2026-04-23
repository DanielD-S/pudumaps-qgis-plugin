"""Convert a QgsVectorLayer into a GeoJSON FeatureCollection ready to POST/
PATCH to the Pudumaps API. Handles CRS reprojection, field serialization
and pre-upload size/count validation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsFeature,
    QgsJsonExporter,
    QgsProject,
    QgsVectorLayer,
)

# Pudumaps API accepts bodies up to 10 MB.
MAX_BODY_MB = 10
MAX_FEATURE_COUNT = 20_000
TARGET_CRS = "EPSG:4326"


class ExportError(Exception):
    """Raised when a layer cannot be exported (too big, wrong type, etc.)."""


@dataclass
class ExportSummary:
    feature_count: int
    size_bytes: int
    source_crs: str
    reprojected: bool

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)


def layer_to_geojson(
    layer: QgsVectorLayer, *, target_crs: str = TARGET_CRS
) -> tuple[dict, ExportSummary]:
    """Return (geojson_dict, summary). Reprojects to WGS84 in-flight if
    the layer's CRS is different. Does not modify the layer.
    """
    if layer is None or not layer.isValid():
        raise ExportError("La capa no es válida.")
    if not isinstance(layer, QgsVectorLayer):
        raise ExportError("Solo se pueden subir capas vectoriales.")

    feature_count = layer.featureCount()
    if feature_count == 0:
        raise ExportError("La capa no tiene features.")
    if feature_count > MAX_FEATURE_COUNT:
        raise ExportError(
            f"La capa tiene {feature_count:,} features (máx {MAX_FEATURE_COUNT:,}). "
            "Simplifica antes de subir."
        )

    source_crs = layer.crs()
    source_authid = source_crs.authid() or "unknown"
    reprojected = source_authid != target_crs

    target = QgsCoordinateReferenceSystem(target_crs)
    transform: QgsCoordinateTransform | None = None
    if reprojected:
        transform = QgsCoordinateTransform(
            source_crs, target, QgsProject.instance().transformContext()
            if QgsProject.instance() is not None
            else QgsCoordinateTransformContext()
        )

    exporter = QgsJsonExporter(layer)
    exporter.setSourceCrs(target)  # so the JSON includes lon/lat

    features_json: list[dict] = []
    for feat in layer.getFeatures():
        if transform is not None:
            f = QgsFeature(feat)
            geom = f.geometry()
            geom.transform(transform)
            f.setGeometry(geom)
            features_json.append(json.loads(exporter.exportFeature(f)))
        else:
            features_json.append(json.loads(exporter.exportFeature(feat)))

    fc: dict = {"type": "FeatureCollection", "features": features_json}
    payload_bytes = len(json.dumps(fc).encode("utf-8"))
    if payload_bytes > MAX_BODY_MB * 1024 * 1024:
        raise ExportError(
            f"La capa ocupa {payload_bytes / 1024 / 1024:.1f} MB (máx {MAX_BODY_MB} MB). "
            "Simplifica la geometría o divide en varias capas."
        )

    summary = ExportSummary(
        feature_count=feature_count,
        size_bytes=payload_bytes,
        source_crs=source_authid,
        reprojected=reprojected,
    )
    return fc, summary


def format_size(bytes_: int) -> str:
    """Human-readable size for UI labels."""
    if bytes_ < 1024:
        return f"{bytes_} B"
    if bytes_ < 1024 * 1024:
        return f"{bytes_ / 1024:.1f} KB"
    return f"{bytes_ / 1024 / 1024:.1f} MB"
