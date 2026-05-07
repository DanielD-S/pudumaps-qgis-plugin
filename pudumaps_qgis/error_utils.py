"""Helpers para sanitizar mensajes de error antes de mostrarlos al usuario.

Originalmente la mayoría de diálogos hacían `f"Error inesperado: {e}"`
que propagaba `repr(e)` directo (incluyendo paths internos del plugin
o detalles que vinieran del body de la API). Ahora pasan por
`safe_error_message` que clamp la longitud y filtra prefijos técnicos
comunes — el detalle crudo se loggea via `qgis.core.QgsMessageLog`
para debugging, pero al user solo le llega un mensaje legible.

Inspirado en `src/lib/errorMessage.ts` del frontend Pudumaps.
"""

from __future__ import annotations

MAX_USER_MESSAGE_LEN = 200

# Prefijos técnicos que aparecen en `str(exception)` y no aportan valor
# al usuario final. Si el mensaje empieza con uno de estos, se omite.
_TECHNICAL_PREFIXES = (
    "Traceback",
    "<class ",
    "RequestException",
    "ConnectionError",
    "HTTPError",
    "ValueError",
    "TypeError",
    "KeyError",
    "AttributeError",
)


def safe_error_message(e: object, max_len: int = MAX_USER_MESSAGE_LEN) -> str:
    """Devuelve un string seguro para mostrar al usuario.

    - Convierte la excepción a su mensaje plano.
    - Strips prefijos técnicos comunes.
    - Cap la longitud a `max_len` con elipsis.
    - Devuelve "Error desconocido" si queda vacío tras limpiar.
    """
    msg = str(e) if e is not None else ""
    msg = msg.strip()

    # Remover prefijos técnicos del comienzo (caso típico: "ValueError: ...")
    for prefix in _TECHNICAL_PREFIXES:
        if msg.startswith(prefix):
            # Buscar primer ":" y tomar lo que viene después
            colon_idx = msg.find(":")
            if colon_idx != -1:
                msg = msg[colon_idx + 1:].strip()
            break

    if not msg:
        return "Error desconocido"

    if len(msg) > max_len:
        msg = msg[: max_len - 1].rstrip() + "…"

    return msg


def log_full_error(context: str, e: object) -> None:
    """Loggea el detalle completo a QgsMessageLog para debugging.

    Best-effort: si QgsMessageLog no está disponible (tests fuera de QGIS),
    no rompe.
    """
    try:
        from qgis.core import Qgis, QgsMessageLog

        QgsMessageLog.logMessage(
            f"{context}: {e!r}", "Pudumaps", level=Qgis.Warning
        )
    except Exception:  # noqa: BLE001
        pass
