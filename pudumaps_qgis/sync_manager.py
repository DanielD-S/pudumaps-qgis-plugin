"""Bidirectional sync between QGIS layers and a Pudumaps project.

State machine per layer (compared to the hash stored at last successful
pull/push in the `pudumaps/last_hash` custom property):

    local_changed = hash(local_geojson) != last_hash
    remote_changed = hash(remote_geojson) != last_hash

    unchanged        local=no  remote=no  → skip
    local_only       local=yes remote=no  → push (PATCH)
    remote_only      local=no  remote=yes → pull (replace features)
    conflict         local=yes remote=yes → user picks: local / remote / skip

Hash is a SHA-256 of the canonical JSON (sorted keys). Normalization of
feature order is best-effort — if both sides reorder features, it'll
register as a false "changed". Acceptable for MVP.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .api_client import LayerSummary, PudumapsClient
from .project_loader import PROP_LAYER_ID, PROP_LAST_HASH


class LayerState(str, Enum):
    UNCHANGED = "unchanged"
    LOCAL_ONLY = "local_only"      # pushable
    REMOTE_ONLY = "remote_only"    # pullable
    CONFLICT = "conflict"          # both sides changed
    NEW_LOCAL = "new_local"        # no remote id yet → push as new
    DELETED_REMOTE = "deleted_remote"  # layer existed, now gone from remote


class SyncAction(str, Enum):
    SKIP = "skip"
    PUSH = "push"
    PULL = "pull"
    USE_LOCAL = "use_local"   # resolves conflict → PATCH with local
    USE_REMOTE = "use_remote"  # resolves conflict → overwrite local
    DELETE_LOCAL = "delete_local"  # remove local layer (if remote gone)


@dataclass
class LayerDiff:
    layer_name: str
    layer_ref: Any  # QgsVectorLayer | None
    remote_id: str | None
    remote_name: str | None
    state: LayerState
    suggested_action: SyncAction
    local_hash: str | None
    remote_hash: str | None
    last_hash: str | None


@dataclass
class SyncResult:
    pushed: int = 0
    pulled: int = 0
    skipped: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)


def canonical_hash(geojson: dict[str, Any]) -> str:
    """Deterministic SHA-256 of a GeoJSON-like dict."""
    if not geojson:
        return ""
    return hashlib.sha256(
        json.dumps(geojson, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def classify(
    local_hash: str | None,
    last_hash: str | None,
    remote_hash: str | None,
) -> LayerState:
    """Pure function — given three hashes, return the sync state."""
    if remote_hash is None:
        # Remote layer gone
        return LayerState.DELETED_REMOTE

    if local_hash is None:
        # Shouldn't happen once linked — treat as remote only so user
        # can pull it fresh.
        return LayerState.REMOTE_ONLY

    local_changed = last_hash is None or local_hash != last_hash
    remote_changed = last_hash is None or remote_hash != last_hash

    # Before the first sync (no last_hash), we can't distinguish who
    # changed — fall back to "conflict if they differ" which prompts
    # the user instead of silently overwriting something.
    if last_hash is None:
        return LayerState.UNCHANGED if local_hash == remote_hash else LayerState.CONFLICT

    if not local_changed and not remote_changed:
        return LayerState.UNCHANGED
    if local_changed and not remote_changed:
        return LayerState.LOCAL_ONLY
    if remote_changed and not local_changed:
        return LayerState.REMOTE_ONLY
    return LayerState.CONFLICT


def suggested_action_for(state: LayerState) -> SyncAction:
    return {
        LayerState.UNCHANGED: SyncAction.SKIP,
        LayerState.LOCAL_ONLY: SyncAction.PUSH,
        LayerState.REMOTE_ONLY: SyncAction.PULL,
        LayerState.CONFLICT: SyncAction.SKIP,  # user must decide
        LayerState.NEW_LOCAL: SyncAction.PUSH,
        LayerState.DELETED_REMOTE: SyncAction.SKIP,
    }[state]


def diff_project(
    client: PudumapsClient,
    project_id: str,
    local_layers: list[Any],
    *,
    local_hash_fn=None,
) -> list[LayerDiff]:
    """Build a LayerDiff list for every layer in the project.

    `local_layers` is the list of QgsVectorLayer instances stamped with
    this `project_id`. `local_hash_fn(layer) -> (hash, last_hash)` is
    injected so this function can be tested without QGIS — in QGIS code
    we pass `_compute_local_hashes`.
    """
    # Fetch all remote layers (summary only — heavier detail fetched lazily)
    remote_summaries: list[LayerSummary] = client.list_layers(project_id)
    remote_by_id = {s.id: s for s in remote_summaries}

    # Hash remotes by pulling full layer (N+1 — fine for MVP at 10s of layers)
    remote_hashes: dict[str, str] = {}
    for s in remote_summaries:
        full = client.get_layer(s.id)
        remote_hashes[s.id] = canonical_hash(full.get("geojson") or {})

    diffs: list[LayerDiff] = []
    seen_remote_ids: set[str] = set()

    for layer in local_layers:
        remote_id = layer.customProperty(PROP_LAYER_ID, "") or None
        if not remote_id:
            # Brand new local layer — push as new
            diffs.append(
                LayerDiff(
                    layer_name=layer.name(),
                    layer_ref=layer,
                    remote_id=None,
                    remote_name=None,
                    state=LayerState.NEW_LOCAL,
                    suggested_action=SyncAction.PUSH,
                    local_hash=None,
                    remote_hash=None,
                    last_hash=None,
                )
            )
            continue

        seen_remote_ids.add(remote_id)
        local_hash, last_hash = local_hash_fn(layer) if local_hash_fn else (None, None)
        remote_hash = remote_hashes.get(remote_id)
        remote_summary = remote_by_id.get(remote_id)

        state = classify(local_hash, last_hash, remote_hash)
        diffs.append(
            LayerDiff(
                layer_name=layer.name(),
                layer_ref=layer,
                remote_id=remote_id,
                remote_name=remote_summary.name if remote_summary else None,
                state=state,
                suggested_action=suggested_action_for(state),
                local_hash=local_hash,
                remote_hash=remote_hash,
                last_hash=last_hash,
            )
        )

    # Any remote layer with no local counterpart → remote_only with a
    # "pull as new" suggestion
    for s in remote_summaries:
        if s.id in seen_remote_ids:
            continue
        diffs.append(
            LayerDiff(
                layer_name=s.name,
                layer_ref=None,
                remote_id=s.id,
                remote_name=s.name,
                state=LayerState.REMOTE_ONLY,
                suggested_action=SyncAction.PULL,
                local_hash=None,
                remote_hash=remote_hashes.get(s.id),
                last_hash=None,
            )
        )

    return diffs


def stamp_hash(layer: Any, geojson_hash: str) -> None:
    """Persist the hash on the layer so we can diff next time."""
    layer.setCustomProperty(PROP_LAST_HASH, geojson_hash)
