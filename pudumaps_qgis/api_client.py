"""HTTP client against the Pudumaps public API.

Uses only stdlib + `requests` (already bundled with QGIS 3.x on all platforms).
Retries on 429 respecting X-RateLimit-Reset, single network layer, typed errors.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests

DEFAULT_BASE_URL = "https://tyftyoexdxrjvxjbdyux.supabase.co/functions/v1/api-v1"
USER_AGENT = "pudumaps-qgis/0.1.0"
DEFAULT_TIMEOUT = 20  # seconds


class PudumapsError(Exception):
    """Raised for any non-2xx response or transport failure."""

    def __init__(self, message: str, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    description: str | None
    visibility: str
    created_at: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Project":
        return cls(
            id=d["id"],
            name=d["name"],
            description=d.get("description"),
            visibility=d.get("visibility", "private"),
            created_at=d["created_at"],
        )


@dataclass(frozen=True)
class LayerSummary:
    id: str
    name: str
    display_order: int
    project_id: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LayerSummary":
        return cls(
            id=d["id"],
            name=d["name"],
            display_order=d.get("display_order", 0),
            project_id=d.get("project_id", ""),
        )


class PudumapsClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        if not api_key:
            raise PudumapsError("API key required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "X-API-Key": api_key,
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json",
            }
        )

    # ── Public methods ────────────────────────────────────────────────────

    def list_projects(self) -> list[Project]:
        data = self._request("GET", "/v1/projects")
        return [Project.from_dict(p) for p in data.get("data", [])]

    def get_project(self, project_id: str) -> Project:
        data = self._request("GET", f"/v1/projects/{project_id}")
        return Project.from_dict(data["data"])

    def create_project(self, name: str, description: str | None = None) -> Project:
        body = {"name": name}
        if description is not None:
            body["description"] = description
        data = self._request("POST", "/v1/projects", json=body)
        return Project.from_dict(data["data"])

    def list_layers(self, project_id: str) -> list[LayerSummary]:
        data = self._request("GET", f"/v1/projects/{project_id}/layers")
        return [LayerSummary.from_dict(layer) for layer in data.get("data", [])]

    def get_layer(self, layer_id: str) -> dict[str, Any]:
        """Returns the full layer including geojson. Caller handles the dict."""
        data = self._request("GET", f"/v1/layers/{layer_id}")
        return data["data"]

    def upload_layer(
        self,
        project_id: str,
        name: str,
        geojson: dict[str, Any],
    ) -> LayerSummary:
        body = {"name": name, "geojson": geojson}
        data = self._request("POST", f"/v1/projects/{project_id}/layers", json=body)
        return LayerSummary.from_dict(data["data"])

    def update_layer(
        self,
        layer_id: str,
        *,
        name: str | None = None,
        geojson: dict[str, Any] | None = None,
    ) -> LayerSummary:
        patch: dict[str, Any] = {}
        if name is not None:
            patch["name"] = name
        if geojson is not None:
            patch["geojson"] = geojson
        if not patch:
            raise PudumapsError("no fields to update")
        data = self._request("PATCH", f"/v1/layers/{layer_id}", json=patch)
        return LayerSummary.from_dict(data["data"])

    def delete_layer(self, layer_id: str) -> None:
        self._request("DELETE", f"/v1/layers/{layer_id}")

    # ── Internal ──────────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        _retries_left: int = 1,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            resp = self._session.request(
                method, url, json=json, timeout=self.timeout
            )
        except requests.RequestException as e:
            raise PudumapsError(f"Network error: {e}") from e

        # Handle 429 with X-RateLimit-Reset awareness
        if resp.status_code == 429 and _retries_left > 0:
            reset_at = resp.headers.get("X-RateLimit-Reset")
            wait = 2.0
            if reset_at:
                try:
                    wait = max(0.5, float(reset_at) - time.time())
                    wait = min(wait, 60)  # cap at 1 min per retry
                except ValueError:
                    pass
            time.sleep(wait)
            return self._request(
                method, path, json=json, _retries_left=_retries_left - 1
            )

        if not 200 <= resp.status_code < 300:
            try:
                body = resp.json()
            except ValueError:
                body = {}
            err = body.get("error") or {}
            raise PudumapsError(
                err.get("message") or f"HTTP {resp.status_code}",
                status=resp.status_code,
                code=err.get("code"),
            )

        if resp.status_code == 204 or not resp.content:
            return {}

        try:
            return resp.json()
        except ValueError as e:
            raise PudumapsError("Invalid JSON response") from e
