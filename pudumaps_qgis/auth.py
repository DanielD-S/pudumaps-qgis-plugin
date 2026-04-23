"""Persist API key + base URL using QgsAuthManager (encrypted) when possible.

Falls back to QSettings (plaintext) if the user hasn't set a master password
for QgsAuthManager. We prefer the encrypted path but we don't want to block
a fresh QGIS install from using the plugin just because the auth DB isn't
initialized yet.
"""

from __future__ import annotations

from typing import NamedTuple

from qgis.core import QgsApplication, QgsAuthMethodConfig
from qgis.PyQt.QtCore import QSettings

from .api_client import DEFAULT_BASE_URL

AUTH_CONFIG_NAME = "pudumaps-api"
SETTINGS_GROUP = "pudumaps"


class ApiCreds(NamedTuple):
    api_key: str
    base_url: str


def _auth_manager():
    return QgsApplication.authManager()


def _has_master_password() -> bool:
    am = _auth_manager()
    return am.masterPasswordIsSet() and not am.masterPasswordHashInDatabase() == ""


def save_credentials(api_key: str, base_url: str = DEFAULT_BASE_URL) -> None:
    """Persist credentials, preferring QgsAuthManager when initialized."""
    base_url = base_url or DEFAULT_BASE_URL

    if _has_master_password():
        cfg = _find_or_create_config()
        cfg_map = {
            "username": "api-key",
            "password": api_key,
            "realm": base_url,
        }
        cfg.setConfig("", "")  # reset any lingering stored-auth config
        cfg.setConfigMap(cfg_map)
        cfg.setName(AUTH_CONFIG_NAME)
        cfg.setMethod("Basic")
        _auth_manager().updateAuthenticationConfig(cfg)
        _persist_auth_id(cfg.id())
    else:
        _save_plain(api_key, base_url)


def load_credentials() -> ApiCreds | None:
    """Returns None if nothing is stored yet."""
    auth_id = _stored_auth_id()
    if auth_id and _has_master_password():
        cfg = QgsAuthMethodConfig()
        if _auth_manager().loadAuthenticationConfig(auth_id, cfg, True):
            cfg_map = cfg.configMap()
            key = cfg_map.get("password") or ""
            url = cfg_map.get("realm") or DEFAULT_BASE_URL
            if key:
                return ApiCreds(api_key=key, base_url=url)

    return _load_plain()


def clear_credentials() -> None:
    auth_id = _stored_auth_id()
    if auth_id:
        _auth_manager().removeAuthenticationConfig(auth_id)
    QSettings().remove(f"{SETTINGS_GROUP}/auth_id")
    QSettings().remove(f"{SETTINGS_GROUP}/api_key")
    QSettings().remove(f"{SETTINGS_GROUP}/base_url")


# ── Internal helpers ─────────────────────────────────────────────────────

def _find_or_create_config() -> QgsAuthMethodConfig:
    auth_id = _stored_auth_id()
    if auth_id:
        cfg = QgsAuthMethodConfig()
        if _auth_manager().loadAuthenticationConfig(auth_id, cfg, True):
            return cfg
    cfg = QgsAuthMethodConfig()
    cfg.setName(AUTH_CONFIG_NAME)
    cfg.setMethod("Basic")
    _auth_manager().storeAuthenticationConfig(cfg)
    return cfg


def _persist_auth_id(auth_id: str) -> None:
    QSettings().setValue(f"{SETTINGS_GROUP}/auth_id", auth_id)


def _stored_auth_id() -> str | None:
    return QSettings().value(f"{SETTINGS_GROUP}/auth_id", "", type=str) or None


def _save_plain(api_key: str, base_url: str) -> None:
    s = QSettings()
    s.setValue(f"{SETTINGS_GROUP}/api_key", api_key)
    s.setValue(f"{SETTINGS_GROUP}/base_url", base_url)


def _load_plain() -> ApiCreds | None:
    s = QSettings()
    key = s.value(f"{SETTINGS_GROUP}/api_key", "", type=str)
    url = s.value(f"{SETTINGS_GROUP}/base_url", DEFAULT_BASE_URL, type=str)
    if not key:
        return None
    return ApiCreds(api_key=key, base_url=url)
