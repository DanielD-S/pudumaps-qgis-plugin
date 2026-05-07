"""HTTP client against the Pudumaps public API.

Uses only stdlib + `requests` (already bundled with QGIS 3.x on all platforms).
Retries on 429 respecting X-RateLimit-Reset, single network layer, typed errors.

Security notes (audit 2026-05-07):
- Base URL is validated via `url_validator.validate_base_url`: HTTPS-only
  (loopback HTTP allowed for dev). Rechazamos `http://evil.example/...` que
  haría leak de la API key en cleartext (H2 ALTO).
- TLS verification: `requests.Session` con `verify=True` por default. NO
  desactivamos TLS en ningún path. NO hay certificate pinning intencional
  (depende del CA bundle de QGIS/Python — aceptable para distribución
  pública).
- Response body size cap: `MAX_RESPONSE_BYTES` rechaza payloads gigantes
  antes de pasarlos a `json.loads` (H4 MEDIO: prevenir OOM si la API o
  un MITM responde con 500 MB de basura).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests

from ._version import get_version
from .url_validator import validate_base_url

DEFAULT_BASE_URL = "https://tyftyoexdxrjvxjbdyux.supabase.co/functions/v1/api-v1"
USER_AGENT = f"pudumaps-qgis/{get_version()}"
DEFAULT_TIMEOUT = 20  # seconds

# Cap defensivo del body de la respuesta. La API de Pudumaps puede
# devolver capas grandes en GET /v1/layers/{id}, pero el plugin valida
# 10 MB en upload — por simetría aceptamos hasta 50 MB en download
# (margen para metadata + reproyección del backend).
MAX_RESPONSE_BYTES = 50 * 1024 * 1024  # 50 MB


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
        # Defense-in-depth: rechazamos URLs no-HTTPS aunque vengan de
        # QSettings (donde un atacante con acceso al disco las podría
        # reescribir a http://). El SettingsDialog también valida en UI
        # — esta validación es la red de seguridad final.
        validated = validate_base_url(base_url)
        self.base_url = validated.rstrip("/")
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
            # stream=True permite chequear Content-Length antes de
            # buffear todo el body. Sin esto, json() carga TODO en
            # memoria sin importar el tamaño.
            resp = self._session.request(
                method, url, json=json, timeout=self.timeout, stream=True
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
            resp.close()
            time.sleep(wait)
            return self._request(
                method, path, json=json, _retries_left=_retries_left - 1
            )

        # Cap defensivo del body. Si el server (o un MITM) declara un
        # Content-Length absurdo, abortamos antes de leer.
        cl = resp.headers.get("Content-Length")
        if cl is not None:
            try:
                if int(cl) > MAX_RESPONSE_BYTES:
                    resp.close()
                    raise PudumapsError(
                        f"Response too large: {cl} bytes "
                        f"(max {MAX_RESPONSE_BYTES})"
                    )
            except ValueError:
                pass  # Content-Length no numérico — caemos al cap por bytes leídos

        # Leer con cap real, también para chunked sin Content-Length.
        try:
            body_bytes = b""
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    body_bytes += chunk
                    if len(body_bytes) > MAX_RESPONSE_BYTES:
                        resp.close()
                        raise PudumapsError(
                            f"Response exceeded {MAX_RESPONSE_BYTES} bytes"
                        )
        except requests.RequestException as e:
            raise PudumapsError(f"Network error reading response: {e}") from e

        if not 200 <= resp.status_code < 300:
            err: dict[str, Any] = {}
            if body_bytes:
                try:
                    parsed = _safe_json_loads(body_bytes)
                    err = parsed.get("error") or {}
                except (ValueError, PudumapsError):
                    err = {}
            raise PudumapsError(
                err.get("message") or f"HTTP {resp.status_code}",
                status=resp.status_code,
                code=err.get("code"),
            )

        if resp.status_code == 204 or not body_bytes:
            return {}

        return _safe_json_loads(body_bytes)


def _safe_json_loads(body_bytes: bytes) -> dict[str, Any]:
    """Parsea JSON garantizando dict en la raíz.

    Audit H4 (2026-05-07): el caller asumía dict pero `json.loads`
    acepta también arrays/strings/numbers/booleans/null en la raíz. Si
    la API devolviera algo no-objeto por error o ataque, el código
    siguiente con `.get(...)` crashearía con AttributeError opaco.
    """
    import json as _json

    try:
        parsed = _json.loads(body_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise PudumapsError("Invalid JSON response") from e
    if not isinstance(parsed, dict):
        raise PudumapsError("Unexpected JSON response shape")
    return parsed
