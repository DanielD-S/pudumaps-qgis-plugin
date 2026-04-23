# Pudumaps QGIS Plugin
# Licensed under GPL-3.0-or-later. See LICENSE in repo root.


def classFactory(iface):
    """Called by QGIS when the plugin is loaded."""
    from .plugin import PudumapsPlugin
    return PudumapsPlugin(iface)
