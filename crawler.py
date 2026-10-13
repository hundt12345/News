# -*- coding: utf-8 -*-
"""Kompatibilitätsschicht für den alten Aufruf ``from crawler import crawl_for_city``.

Die eigentliche Logik ist in das Paket :mod:`news` gewandert:

===========  ==========================================================
places       Ortsauflösung (86 Stadtteile, 9 Bezirke, kölsche Veedel)
sources      Quellen-Plan inkl. Reddit/Foren
fetch        HTTP mit Browser-UA, robots.txt, Reddit-Kaskade
relevance    Veedel-Filter, Kategorien, Dedup, Vielfalt
aggregator   paralleles Holen, Cache, Gruppierung
===========  ==========================================================

``SOURCES`` existiert weiterhin als lesbare Übersicht – die App baut ihre
Quellen aber jetzt **dynamisch** aus der Eingabe. Genau das war der Fehler:
Früher war hier Köln-Deutz fest verdrahtet, deshalb lieferte jeder Stadtteil
dieselben Deutz-Artikel.
"""

from __future__ import annotations

from news.aggregator import crawl_for_city  # noqa: F401
from news.places import BEZIRKE, resolve_place  # noqa: F401
from news.sources import (  # noqa: F401
    EXPRESS_FEED,
    KSTA_FEED,
    RUNDSCHAU_FEED,
    build_plan,
    stadtweite_quellen,
)


def quellen_fuer(ort: str) -> list[dict]:
    """Übersicht, welche Quellen für einen Ort geholt würden."""
    plan = build_plan(resolve_place(ort))
    return [
        {"name": s.name, "typ": s.kind, "gruppe": s.group,
         "url": s.url or f"https://www.reddit.com{s.path}", "scope": s.scope}
        for s in plan
    ]


# Lesbare Übersicht der festen, stadtweiten Quellen (Dokumentation/Zweck)
SOURCES = {s.name: (s.url or s.path, s.scope) for s in stadtweite_quellen()}


__all__ = ["crawl_for_city", "build_plan", "quellen_fuer", "SOURCES",
           "resolve_place", "BEZIRKE", "KSTA_FEED", "RUNDSCHAU_FEED",
           "EXPRESS_FEED"]
