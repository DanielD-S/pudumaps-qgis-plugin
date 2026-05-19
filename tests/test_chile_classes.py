"""Tests del re-etiquetado de clases por ecorregión chilena (Nivel 1)."""

from __future__ import annotations

import pytest

from pudumaps_qgis.ai.chile_classes import (
    ECOREGIONS,
    ecoregion_for_bbox,
    ecoregion_name,
    translate_class,
)


# ── Detección de ecorregión ──────────────────────────────────────────────


def test_ecoregion_zona_central():
    """Santiago centro: bbox ~ (-70.7, -33.5, -70.6, -33.4)."""
    eco = ecoregion_for_bbox((-70.7, -33.5, -70.6, -33.4))
    assert eco == "matorral_esclerofilo"


def test_ecoregion_atacama():
    """Calama: bbox ~ (-68.95, -22.5, -68.9, -22.45)."""
    eco = ecoregion_for_bbox((-68.95, -22.5, -68.9, -22.45))
    assert eco == "desierto_costero"


def test_ecoregion_patagonia_sur():
    """Punta Arenas: bbox ~ (-71, -53.2, -70.9, -53.1)."""
    eco = ecoregion_for_bbox((-71, -53.2, -70.9, -53.1))
    assert eco == "estepa_patagonica"


def test_ecoregion_bosque_lluvioso_los_rios():
    """Valdivia: bbox ~ (-73.3, -39.9, -73.2, -39.8)."""
    eco = ecoregion_for_bbox((-73.3, -39.9, -73.2, -39.8))
    assert eco == "bosque_templado_lluvioso"


def test_ecoregion_chiloe():
    """Castro: bbox ~ (-73.8, -42.6, -73.7, -42.5)."""
    eco = ecoregion_for_bbox((-73.8, -42.6, -73.7, -42.5))
    assert eco == "bosque_siempreverde"


def test_ecoregion_fuera_de_chile_buenos_aires():
    """BA: bbox ~ (-58.5, -34.7, -58.4, -34.6) — fuera del rango chileno."""
    assert ecoregion_for_bbox((-58.5, -34.7, -58.4, -34.6)) is None


def test_ecoregion_fuera_de_chile_lima():
    """Lima: bbox ~ (-77.05, -12.05, -77, -12) — lat fuera rango chileno."""
    assert ecoregion_for_bbox((-77.05, -12.05, -77, -12)) is None


def test_ecoregion_none_bbox():
    assert ecoregion_for_bbox(None) is None


def test_ecoregion_bbox_invalido():
    """bbox con menos elementos → None, no crash."""
    assert ecoregion_for_bbox((1, 2)) is None  # type: ignore[arg-type]
    assert ecoregion_for_bbox("garbage") is None  # type: ignore[arg-type]


def test_ecoregion_name_returns_human_label():
    name = ecoregion_name("matorral_esclerofilo")
    assert name is not None
    assert "central" in name.lower() or "esclerófilo" in name.lower()


def test_ecoregion_name_unknown_returns_none():
    assert ecoregion_name("xxx") is None
    assert ecoregion_name(None) is None


# ── Traducción de clases ─────────────────────────────────────────────────


def test_translate_shrubland_zona_central():
    """En Santiago shrubland → matorral esclerófilo."""
    out = translate_class("shrubland", bbox=(-70.7, -33.5, -70.6, -33.4))
    assert "esclerófilo" in out


def test_translate_shrubland_patagonia():
    """En Patagonia shrubland → matorral patagónico."""
    out = translate_class("shrubland", bbox=(-71, -53.2, -70.9, -53.1))
    assert "patagónico" in out


def test_translate_forest_valdivia():
    """En Valdivia forest → bosque templado lluvioso."""
    out = translate_class("forest", bbox=(-73.3, -39.9, -73.2, -39.8))
    assert "lluvioso" in out


def test_translate_water_atacama():
    """En Atacama water → 'agua o salar' (contexto chileno específico)."""
    out = translate_class("water", bbox=(-68.95, -22.5, -68.9, -22.45))
    assert "salar" in out.lower()


def test_translate_without_bbox_uses_generic():
    """Sin bbox usa traducción genérica en español."""
    assert translate_class("shrubland") == "matorral"
    assert translate_class("forest") == "bosque"
    assert translate_class("water") == "agua"


def test_translate_built_is_consistent():
    """`built` no depende de ecorregión — siempre 'área urbana o construida'."""
    out1 = translate_class("built", bbox=(-70.7, -33.5, -70.6, -33.4))
    out2 = translate_class("built", bbox=(-71, -53.2, -70.9, -53.1))
    assert out1 == out2
    assert "urbana" in out1


def test_translate_unknown_class_falls_back():
    """Clase desconocida se devuelve con primera letra mayúscula."""
    assert translate_class("xyzzy") == "Xyzzy"


def test_translate_empty_string():
    assert translate_class("") == ""


def test_translate_case_insensitive():
    """Input puede venir en mayúsculas/minúsculas."""
    a = translate_class("FOREST", bbox=(-73.3, -39.9, -73.2, -39.8))
    b = translate_class("forest", bbox=(-73.3, -39.9, -73.2, -39.8))
    assert a == b
