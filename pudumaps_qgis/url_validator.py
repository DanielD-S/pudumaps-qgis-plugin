"""HTTPS-only URL validation for the Pudumaps API base URL.

Audit 2026-05-07 (H2 ALTO): the base URL field accepted any scheme,
so a user (or attacker via QSettings tampering / social engineering)
could set `http://evil.example/...` and the API key would travel
in cleartext on every request.

This validator rejects non-HTTPS URLs with a clear error, except for
loopback addresses (127.0.0.1, localhost) which are allowed for local
dev / staging without TLS termination.
"""

from __future__ import annotations

from urllib.parse import urlparse


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class InvalidBaseUrlError(ValueError):
    """Raised when a base URL does not meet the HTTPS-only policy."""


def validate_base_url(url: str) -> str:
    """Returns the URL if valid, raises InvalidBaseUrlError otherwise.

    Rules:
      - Must parse as a URL.
      - Scheme must be `https`. Exception: `http` allowed only when host
        is loopback (localhost, 127.0.0.1, ::1).
      - Must have a host.
    """
    if not url or not isinstance(url, str):
        raise InvalidBaseUrlError("La URL no puede estar vacía.")

    url = url.strip()
    parsed = urlparse(url)

    if not parsed.scheme:
        raise InvalidBaseUrlError(
            "La URL debe empezar con https:// (o http://localhost para dev)."
        )

    if not parsed.hostname:
        raise InvalidBaseUrlError("La URL no incluye un host válido.")

    host = parsed.hostname.lower()
    is_loopback = host in _LOOPBACK_HOSTS

    if parsed.scheme == "https":
        return url

    if parsed.scheme == "http" and is_loopback:
        return url

    raise InvalidBaseUrlError(
        f"Esquema '{parsed.scheme}://' no permitido. "
        "La API key se enviaría en claro. Usa https:// "
        "(http:// solo se permite contra localhost para desarrollo)."
    )
