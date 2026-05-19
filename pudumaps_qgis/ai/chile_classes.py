"""Re-etiquetado de clases de landcover a vocabulario chileno (Nivel 1).

Los modelos pre-entrenados de geoai devuelven clases con nombres genéricos
en inglés (`shrubland`, `grassland`, `bare`, `forest`). Esta tabla las
traduce a vocabulario chileno de ecorregión cuando se puede inferir la
zona del país desde el bbox del raster.

NO es machine learning — es lookup determinístico basado en latitud y, en
algunos casos, longitud. Suficiente para Nivel 1 ("orto chilena + clases
en español"). Para precisión real necesitaríamos modelos finetuneados
sobre datasets chilenos (Nivel 2, planeado v0.8).

Uso típico:

    from .chile_classes import translate_class

    spanish = translate_class("shrubland", bbox=(-71.5, -33.5, -71.4, -33.4))
    # → "matorral esclerófilo"  (zona central → Mediterranean shrubland)

    spanish = translate_class("shrubland", bbox=(-71.5, -52, -71.4, -51.9))
    # → "estepa patagónica"  (sur → Patagonian steppe)
"""

from __future__ import annotations

from typing import Optional, Tuple

# Ecorregiones chilenas simplificadas, por latitud aproximada.
# Fuente: clasificación bioclimática Luebert & Pliscoff (2017) simplificada.
# Solo se usan los rangos lat. Es lookup rápido, no precisión científica.
ECOREGIONS = [
    # (lat_max, lat_min, key, nombre_humano)
    (-17.5, -27.0, "desierto_costero",
     "Desierto costero / Atacama"),
    (-27.0, -33.0, "matorral_serofilo",
     "Matorral xerófilo / Norte chico"),
    (-33.0, -38.0, "matorral_esclerofilo",
     "Matorral esclerófilo / Zona central"),
    (-38.0, -42.0, "bosque_templado_lluvioso",
     "Bosque templado lluvioso / Sur"),
    (-42.0, -47.0, "bosque_siempreverde",
     "Bosque siempreverde / Patagonia norte"),
    (-47.0, -56.0, "estepa_patagonica",
     "Estepa patagónica / Patagonia sur"),
]

# Mapeo nombre genérico (en inglés, lowercased) → traducción según ecorregión.
# Si el nombre no está aquí, se devuelve tal cual (con primera letra mayúscula).
TRANSLATIONS = {
    "shrubland": {
        "desierto_costero": "matorral desértico costero",
        "matorral_serofilo": "matorral xerófilo",
        "matorral_esclerofilo": "matorral esclerófilo",
        "bosque_templado_lluvioso": "matorral templado",
        "bosque_siempreverde": "matorral siempreverde",
        "estepa_patagonica": "matorral patagónico",
    },
    "grassland": {
        "desierto_costero": "pastizal árido",
        "matorral_serofilo": "pradera xerófita",
        "matorral_esclerofilo": "pradera mediterránea",
        "bosque_templado_lluvioso": "pradera templada",
        "bosque_siempreverde": "pradera siempreverde",
        "estepa_patagonica": "estepa patagónica",
    },
    "forest": {
        "matorral_esclerofilo": "bosque esclerófilo",
        "bosque_templado_lluvioso": "bosque templado lluvioso",
        "bosque_siempreverde": "bosque siempreverde valdiviano",
        "estepa_patagonica": "bosque caducifolio magallánico",
    },
    "bare": {
        # Suelo desnudo: nombre cambia poco por ecorregión, pero en
        # Atacama tiene connotación específica.
        "desierto_costero": "desierto",
        "estepa_patagonica": "suelo desnudo / pampa",
    },
    "water": {
        # Agua se queda como "agua" salvo en zonas con salares.
        "desierto_costero": "agua o salar",
    },
    "built": "área urbana o construida",
    "built_up": "área urbana o construida",
    "urban": "área urbana o construida",
    "agriculture": "agricultura",
    "cropland": "cultivos",
    "snow": "nieve",
    "ice": "hielo / glaciar",
    "wetland": "humedal",
}

# Default fallback genérico (case insensitive) → español neutro.
GENERIC_ES = {
    "shrubland": "matorral",
    "grassland": "pradera",
    "forest": "bosque",
    "bare": "suelo desnudo",
    "water": "agua",
}


def ecoregion_for_bbox(bbox: Optional[Tuple[float, float, float, float]]) -> Optional[str]:
    """Devuelve la key de ecorregión chilena para el centro del bbox.

    bbox = (xmin, ymin, xmax, ymax) en EPSG:4326. Si está fuera de Chile
    o el bbox no se provee, devuelve None.
    """
    if bbox is None:
        return None
    try:
        xmin, ymin, xmax, ymax = bbox
    except (ValueError, TypeError):
        return None

    cx = (xmin + xmax) / 2.0
    cy = (ymin + ymax) / 2.0

    # Chile continental: longitud aproximadamente [-76, -66], lat [-56, -17.5].
    if not (-76 <= cx <= -66):
        return None
    if not (-56 <= cy <= -17.5):
        return None

    for lat_max, lat_min, key, _name in ECOREGIONS:
        if lat_min <= cy <= lat_max:
            return key
    return None


def ecoregion_name(key: Optional[str]) -> Optional[str]:
    """Nombre humano (es) para una key de ecorregión, o None si no existe."""
    if key is None:
        return None
    for _lat_max, _lat_min, k, name in ECOREGIONS:
        if k == key:
            return name
    return None


def translate_class(
    class_name: str,
    bbox: Optional[Tuple[float, float, float, float]] = None,
) -> str:
    """Traduce el nombre de una clase genérica a español + ecorregión.

    Args:
        class_name: nombre que devuelve el modelo (ej. "shrubland",
            "forest", "Built").
        bbox: bbox del raster en EPSG:4326 para inferir ecorregión.
            Si es None, se devuelve la traducción genérica en español.

    Returns:
        String en español. Si el nombre no se reconoce, se devuelve la
        versión con primera letra en mayúscula como fallback seguro.
    """
    if not class_name:
        return ""

    key = class_name.strip().lower()
    eco_key = ecoregion_for_bbox(bbox)

    entry = TRANSLATIONS.get(key)
    if isinstance(entry, dict):
        # Tabla por ecorregión.
        if eco_key and eco_key in entry:
            return entry[eco_key]
        # Fallback genérico si la ecorregión no está cubierta.
        return GENERIC_ES.get(key, class_name.capitalize())

    if isinstance(entry, str):
        return entry

    # Fallback final: nombre genérico en español, o el original con mayúscula.
    return GENERIC_ES.get(key, class_name.capitalize())


__all__ = [
    "ECOREGIONS",
    "TRANSLATIONS",
    "ecoregion_for_bbox",
    "ecoregion_name",
    "translate_class",
]
