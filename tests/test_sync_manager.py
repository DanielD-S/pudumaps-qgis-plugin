"""Unit tests for sync_manager — hash + classify state machine.

Pure Python, no QGIS dependencies.
"""

from __future__ import annotations

import sys
from types import ModuleType


def _stub_qgis_core() -> None:
    """project_loader (imported transitively) needs qgis.core stubbed."""
    qgis = ModuleType("qgis")
    core = ModuleType("qgis.core")

    class _Stub:
        def __init__(self, *a, **kw):
            pass

        def __call__(self, *a, **kw):
            return self

        def __getattr__(self, _name):
            return _Stub()

    for name in (
        "QgsFillSymbol",
        "QgsLineSymbol",
        "QgsMarkerSymbol",
        "QgsProject",
        "QgsSingleSymbolRenderer",
        "QgsVectorLayer",
        "QgsWkbTypes",
        "QgsRectangle",
    ):
        setattr(core, name, _Stub)

    qgis.core = core
    sys.modules.setdefault("qgis", qgis)
    sys.modules["qgis.core"] = core


_stub_qgis_core()

from pudumaps_qgis.sync_manager import (  # noqa: E402
    LayerState,
    SyncAction,
    canonical_hash,
    classify,
    suggested_action_for,
)


# ── Hash ─────────────────────────────────────────────────────────────────


def test_canonical_hash_deterministic():
    fc1 = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": None, "properties": {"a": 1, "b": 2}}]}
    fc2 = {"type": "FeatureCollection", "features": [{"properties": {"b": 2, "a": 1}, "geometry": None, "type": "Feature"}]}
    # Key order must not change the hash
    assert canonical_hash(fc1) == canonical_hash(fc2)


def test_canonical_hash_different_features_differ():
    fc1 = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}}]}
    fc2 = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]}}]}
    assert canonical_hash(fc1) != canonical_hash(fc2)


def test_canonical_hash_empty():
    assert canonical_hash({}) == ""


# ── Classify ─────────────────────────────────────────────────────────────


def test_classify_unchanged():
    h = "abc"
    assert classify(h, h, h) == LayerState.UNCHANGED


def test_classify_local_only():
    assert classify("new", "old", "old") == LayerState.LOCAL_ONLY


def test_classify_remote_only():
    assert classify("old", "old", "new") == LayerState.REMOTE_ONLY


def test_classify_conflict():
    assert classify("local_new", "old", "remote_new") == LayerState.CONFLICT


def test_classify_first_sync_matching():
    # No last_hash yet and both sides match → safe to consider unchanged
    assert classify("same", None, "same") == LayerState.UNCHANGED


def test_classify_first_sync_differ():
    # No last_hash and hashes differ → we can't tell who's right → conflict
    assert classify("a", None, "b") == LayerState.CONFLICT


def test_classify_remote_deleted():
    assert classify("any", "any", None) == LayerState.DELETED_REMOTE


# ── Suggested actions ────────────────────────────────────────────────────


def test_suggested_actions_mapping():
    assert suggested_action_for(LayerState.UNCHANGED) == SyncAction.SKIP
    assert suggested_action_for(LayerState.LOCAL_ONLY) == SyncAction.PUSH
    assert suggested_action_for(LayerState.REMOTE_ONLY) == SyncAction.PULL
    # Conflict defaults to SKIP so user has to pick explicitly
    assert suggested_action_for(LayerState.CONFLICT) == SyncAction.SKIP
    assert suggested_action_for(LayerState.NEW_LOCAL) == SyncAction.PUSH
    assert suggested_action_for(LayerState.DELETED_REMOTE) == SyncAction.SKIP
