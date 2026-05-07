"""Single source of truth for the plugin version.

Reads from metadata.txt at import time so the User-Agent header in
api_client.py and any future telemetry stay aligned with the actual
release version (bug H6 in security audit 2026-05-07: User-Agent was
hardcoded to 0.1.0 while the plugin shipped 0.5.0).
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

_METADATA_PATH = os.path.join(os.path.dirname(__file__), "metadata.txt")
_VERSION_RE = re.compile(r"^version\s*=\s*(\S+)\s*$", re.MULTILINE)
_FALLBACK_VERSION = "0.0.0"


@lru_cache(maxsize=1)
def get_version() -> str:
    """Returns the plugin version string (e.g. "0.5.0")."""
    try:
        with open(_METADATA_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        match = _VERSION_RE.search(content)
        if match:
            return match.group(1)
    except OSError:
        pass
    return _FALLBACK_VERSION


__version__ = get_version()
