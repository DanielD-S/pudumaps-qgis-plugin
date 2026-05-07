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


def is_encrypted_storage_available() -> bool:
    """True si QgsAuthManager está listo para cifrar.

    Audit H1 ALTO (2026-05-07): el plugin caía a QSettings plaintext
    silenciosamente cuando el master password no estaba seteado. Ahora
    `SettingsDialog` consulta esta función ANTES de guardar y muestra
    un warning explícito si va a degradar.
    """
    return _has_master_password()


def save_credentials(
    api_key: str,
    base_url: str = DEFAULT_BASE_URL,
    *,
    allow_plaintext_fallback: bool = False,
) -> None:
    """Persist credentials, preferring QgsAuthManager when initialized.

    Args:
        api_key: The API key to store.
        base_url: API base URL.
        allow_plaintext_fallback: Si False (default) y QgsAuthManager
            no está listo, se levanta `PlaintextStorageRefused`. Si
            True, se guarda en QSettings sin cifrar (caller debe haber
            obtenido confirmación explícita del usuario).
    """
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
        # Si quedaba algo viejo en plaintext de una instalación anterior,
        # limpiarlo para no dejar la key duplicada y sin cifrar.
        _wipe_plain()
        return

    if not allow_plaintext_fallback:
        raise PlaintextStorageRefused(
            "El gestor de autenticación de QGIS no tiene master password "
            "configurado. Guardar la API key sin cifrar requiere "
            "confirmación explícita del usuario."
        )
    _save_plain(api_key, base_url)


class PlaintextStorageRefused(RuntimeError):
    """Raised by save_credentials() cuando se rechaza fallback plaintext."""


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


def clear_credentials() -> bool:
    """Borra credenciales del QgsAuthManager y de QSettings.

    Returns:
        True si pudo borrar la entry cifrada (o si no había). False si
        existía una entry cifrada pero no se pudo eliminar (típicamente
        porque el master password no está set en sesión). En ambos
        casos las entries de QSettings sí se borran.

    Audit H8 BAJO (2026-05-07): antes esta función llamaba
    removeAuthenticationConfig sin chequear el return; si fallaba, la
    entry cifrada sobrevivía y el caller no se enteraba.
    """
    auth_cleared = True
    auth_id = _stored_auth_id()
    if auth_id:
        if _has_master_password():
            ok = _auth_manager().removeAuthenticationConfig(auth_id)
            auth_cleared = bool(ok)
        else:
            auth_cleared = False
    _wipe_plain()
    QSettings().remove(f"{SETTINGS_GROUP}/auth_id")
    return auth_cleared


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


def _wipe_plain() -> None:
    s = QSettings()
    s.remove(f"{SETTINGS_GROUP}/api_key")
    s.remove(f"{SETTINGS_GROUP}/base_url")


def _load_plain() -> ApiCreds | None:
    s = QSettings()
    key = s.value(f"{SETTINGS_GROUP}/api_key", "", type=str)
    url = s.value(f"{SETTINGS_GROUP}/base_url", DEFAULT_BASE_URL, type=str)
    if not key:
        return None
    return ApiCreds(api_key=key, base_url=url)
