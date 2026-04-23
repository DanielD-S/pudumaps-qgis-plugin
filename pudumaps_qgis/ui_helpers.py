"""Reusable UI helpers: Pudumaps branded header and native QGIS toasts."""

from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

PLUGIN_DIR = Path(__file__).resolve().parent
LOGO_PNG = str(PLUGIN_DIR / "icons" / "pudumaps-logo.png")


def build_header(title: str, subtitle: str = "", logo_height: int = 48) -> QFrame:
    """Return a QFrame with the Pudumaps logo on the left and a
    title/subtitle pair on the right. Drop it at the top of any dialog
    for consistent branding.
    """
    frame = QFrame()
    frame.setFrameShape(QFrame.NoFrame)
    frame.setContentsMargins(0, 0, 0, 0)

    hbox = QHBoxLayout(frame)
    hbox.setContentsMargins(0, 0, 0, 8)
    hbox.setSpacing(12)

    logo = QLabel()
    pm = QPixmap(LOGO_PNG)
    if not pm.isNull():
        pm = pm.scaledToHeight(logo_height, Qt.SmoothTransformation)
        logo.setPixmap(pm)
    logo.setFixedHeight(logo_height)
    hbox.addWidget(logo, 0, Qt.AlignTop)

    text_col = QVBoxLayout()
    text_col.setSpacing(0)
    text_col.setContentsMargins(0, 4, 0, 0)

    title_label = QLabel(title)
    title_label.setObjectName("pudumapsHeaderTitle")
    text_col.addWidget(title_label)

    if subtitle:
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("pudumapsHeaderSubtitle")
        subtitle_label.setWordWrap(True)
        text_col.addWidget(subtitle_label)

    text_col.addStretch()
    hbox.addLayout(text_col, 1)

    return frame


def separator() -> QFrame:
    """Thin horizontal separator to put between header and content."""
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    line.setStyleSheet("color: #e5e7eb;")
    return line


# ── Native QGIS toasts via iface.messageBar() ────────────────────────────


def toast_success(iface, message: str, title: str = "Pudumaps", duration: int = 4) -> None:
    """Show a green success toast at the top of the QGIS map canvas.
    Replaces modal QMessageBox.information() calls."""
    if iface is None:
        return
    from qgis.core import Qgis

    iface.messageBar().pushMessage(title, message, level=Qgis.Success, duration=duration)


def toast_info(iface, message: str, title: str = "Pudumaps", duration: int = 4) -> None:
    if iface is None:
        return
    from qgis.core import Qgis

    iface.messageBar().pushMessage(title, message, level=Qgis.Info, duration=duration)


def toast_warning(iface, message: str, title: str = "Pudumaps", duration: int = 6) -> None:
    if iface is None:
        return
    from qgis.core import Qgis

    iface.messageBar().pushMessage(title, message, level=Qgis.Warning, duration=duration)


def toast_error(iface, message: str, title: str = "Pudumaps", duration: int = 8) -> None:
    if iface is None:
        return
    from qgis.core import Qgis

    iface.messageBar().pushMessage(title, message, level=Qgis.Critical, duration=duration)
