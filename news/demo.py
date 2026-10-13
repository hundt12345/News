# -*- coding: utf-8 -*-
"""Demo-Modus: echte Feed-Inhalte aus ``tests/fixtures`` statt Netzwerk.

Zwei Zwecke:

* **Entwicklung/CI ohne Internet** – die Pipeline (Ortsauflösung, Veedel-Filter,
  Kategorien, Dedup, Oberfläche) lässt sich vollständig durchtesten.
* **Vorschau**, wenn der Rechner die Nachrichtenquellen gerade nicht erreicht.

Die Fixtures sind **echte** Feeds, die am 13.10.2026 von ksta.de, express.de,
koeln.polizei.nrw, stadt-koeln.de und reddit.com geladen wurden.

Aktivieren:  ``NEWS_DEMO=1``  oder  ``/?ort=Nippes&demo=1``
"""

from __future__ import annotations

import os
import re

from .fetch import Item, SourceResult, parse_feed

FIXTURE_VERZ = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "fixtures")

# (Muster in der Feed-URL, Fixture-Datei, Anzeigename)
DEMO_MAP: list[tuple[str, str, str]] = [
    ("koeln/nippes/nippes-veedel/index.rss", "ksta_nippes_bezirk.xml", "KSTA · Nippes"),
    ("koeln/nippes/nippes/index.rss", "ksta_nippes_bezirk.xml", "KSTA · Nippes"),
    ("koeln/nippes/index.rss", "ksta_nippes_bezirk.xml", "KSTA · Bezirk Nippes"),
    ("koeln/koelner-innenstadt/deutz/index.rss", "ksta_deutz_stadtteil.xml", "KSTA · Deutz"),
    ("koeln/koelner-innenstadt/index.rss", "ksta_deutz_stadtteil.xml",
     "KSTA · Bezirk Innenstadt"),
    ("feed.express.de", "express_koeln.xml", "EXPRESS Köln"),
    ("polizei.nrw", "polizei_koeln.xml", "Polizei Köln (Presseportal NRW)"),
    ("stadt-koeln.de", "stadt_koeln.xml", "Stadt Köln · Pressemeldungen"),
    ("/r/Koeln/", "reddit_koeln.atom", "Reddit r/Koeln · neu"),
    ("/r/cologne/", "reddit_koeln.atom", "Reddit r/cologne · neu"),
]

_KSTA_PFAD = re.compile(r"/koeln/([a-z\-]+)/")


def verfuegbar() -> bool:
    return os.path.isdir(FIXTURE_VERZ) and bool(os.listdir(FIXTURE_VERZ))


def _inhalt(datei: str) -> bytes:
    with open(os.path.join(FIXTURE_VERZ, datei), "rb") as fh:
        return fh.read()


def demo_quelle(name: str, url: str, pfad: str = "", gruppe: str = "medien",
                art: str = "news") -> SourceResult:
    """Ersetzt einen echten Abruf durch den Inhalt einer Fixture-Datei."""
    ziel = url or pfad

    datei, anzeige = "", name
    for muster, fix, label in DEMO_MAP:
        if muster in ziel:
            datei, anzeige = fix, label
            break

    if not datei:
        # generische KSTA-Stadtteilfeeds: Bezirksfeed zuordnen, sonst leer
        m = _KSTA_PFAD.search(ziel)
        if m:
            bezirk = m.group(1)
            if "nippes" in ziel:
                datei, anzeige = "ksta_nippes_bezirk.xml", name
            elif "/deutz/" in ziel:
                datei, anzeige = "ksta_deutz_stadtteil.xml", name

    if not datei:
        return SourceResult(name=name, url=ziel, ok=True, items=[], group=gruppe,
                            used="Demo: keine hinterlegten Daten")

    items: list[Item] = parse_feed(_inhalt(datei), anzeige, ziel, kind=art)
    return SourceResult(name=name, url=ziel, ok=True, items=items, group=gruppe,
                        used=f"Demo-Daten ({datei})")


HINWEIS = (
    "Demo-Modus aktiv: angezeigt werden originale, am 13.10.2026 gespeicherte "
    "Feeds (Beispiele für Nippes, Deutz und Ehrenfeld) – kein Live-Abruf. "
    "Für den Echtbetrieb den Parameter demo=1 weglassen bzw. NEWS_DEMO=0 setzen.")
