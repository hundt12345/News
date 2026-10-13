# -*- coding: utf-8 -*-
"""Lokal-News-Aggregator für Köln (und das Umland).

Modulaufbau
-----------
places      Ortsauflösung: Stadtbezirke, die 86 Stadtteile, kölsche Veedel, Aliase
sources     Welche Feeds/Foren für einen Ort geholt werden (Quellen-Plan)
fetch       HTTP-Layer: Browser-UA, robots.txt, RSS/HTML/Reddit-Parser, Retries
relevance   Veedel-Filter, Kategorien, Dedup, Ranking
aggregator  Orchestrierung: parallel holen, cachen, gruppieren
weather     Wetter (OpenWeatherMap oder Open-Meteo, beides optional)
"""

from .aggregator import aggregate_news  # noqa: F401
from .places import resolve_place, Place  # noqa: F401

__all__ = ["aggregate_news", "resolve_place", "Place"]
