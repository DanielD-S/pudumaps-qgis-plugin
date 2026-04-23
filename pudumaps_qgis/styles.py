"""Pudumaps QSS stylesheet.

Applied to every dialog via `apply_pudumaps_style(widget)`. Uses the
Pudumaps green palette matching the web UI:
    primary         #22c55e
    primary_hover   #16a34a
    primary_active  #15803d
    on_primary      #ffffff
    danger          #ef4444
    warn            #f59e0b
    muted           #6b7280
    info            #3b82f6
"""

from __future__ import annotations

from qgis.PyQt.QtWidgets import QWidget

PUDUMAPS_GREEN = "#22c55e"
PUDUMAPS_GREEN_HOVER = "#16a34a"
PUDUMAPS_GREEN_ACTIVE = "#15803d"

# Kept minimal — we don't override QGIS's own theme. We only paint
# our own custom widgets with Pudumaps identity: primary buttons,
# table header selection, link/focus rings.
STYLESHEET = f"""
/* ── Dialog host ──────────────────────────────────────────────── */
QDialog#PudumapsDialog {{
    background: palette(window);
}}

/* ── Primary buttons (upload, apply, save…) ──────────────────── */
QPushButton#pudumapsPrimary,
QDialogButtonBox QPushButton[default="true"] {{
    background-color: {PUDUMAPS_GREEN};
    color: white;
    border: 1px solid {PUDUMAPS_GREEN_HOVER};
    border-radius: 4px;
    padding: 6px 14px;
    font-weight: 600;
    min-height: 24px;
}}
QPushButton#pudumapsPrimary:hover,
QDialogButtonBox QPushButton[default="true"]:hover {{
    background-color: {PUDUMAPS_GREEN_HOVER};
    border-color: {PUDUMAPS_GREEN_ACTIVE};
}}
QPushButton#pudumapsPrimary:pressed,
QDialogButtonBox QPushButton[default="true"]:pressed {{
    background-color: {PUDUMAPS_GREEN_ACTIVE};
}}
QPushButton#pudumapsPrimary:disabled,
QDialogButtonBox QPushButton[default="true"]:disabled {{
    background-color: #9ca3af;
    border-color: #6b7280;
    color: #e5e7eb;
}}

/* ── Secondary buttons — keep QGIS native look but with green accent on focus */
QPushButton:focus {{
    border-color: {PUDUMAPS_GREEN};
}}

/* ── Line edits with green focus ring ────────────────────────── */
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
    border: 1px solid {PUDUMAPS_GREEN};
}}

/* ── Tables (projects list, sync status) ─────────────────────── */
QTableWidget {{
    gridline-color: #e5e7eb;
    alternate-background-color: #f9fafb;
    selection-background-color: {PUDUMAPS_GREEN};
    selection-color: white;
}}
QTableWidget::item:selected {{
    background-color: {PUDUMAPS_GREEN};
}}
QHeaderView::section {{
    background-color: #f3f4f6;
    color: #374151;
    border: none;
    border-bottom: 2px solid {PUDUMAPS_GREEN};
    padding: 6px 8px;
    font-weight: 600;
}}

/* ── Progress bar ────────────────────────────────────────────── */
QProgressBar {{
    border: 1px solid #d1d5db;
    border-radius: 4px;
    text-align: center;
    background-color: #f3f4f6;
    min-height: 18px;
}}
QProgressBar::chunk {{
    background-color: {PUDUMAPS_GREEN};
    border-radius: 3px;
}}

/* ── Header label (big logo + title) ─────────────────────────── */
QLabel#pudumapsHeaderTitle {{
    font-size: 18px;
    font-weight: 700;
    color: #1f2937;
}}
QLabel#pudumapsHeaderSubtitle {{
    font-size: 12px;
    color: #6b7280;
}}
"""


def apply_pudumaps_style(widget: QWidget) -> None:
    """Apply the Pudumaps stylesheet to a dialog and its children."""
    widget.setObjectName("PudumapsDialog")
    widget.setStyleSheet(STYLESHEET)
