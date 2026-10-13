# -*- coding: utf-8 -*-
"""Quellen-Plan: Welche Feeds & Foren werden für welchen Ort geholt?

Früher stand hier ein hart verdrahtetes ``SOURCES``-Dict, das **immer** auf
Köln-Deutz zeigte. Jetzt wird der Plan pro Eingabe gebaut:

``Köln-Ehrenfeld`` ->  KSTA-Stadtteilfeed Ehrenfeld
                       KSTA-Bezirksfeed Ehrenfeld
                       Express/Rundschau/koeln.de (stadtweit, wird gefiltert)
                       Polizei Köln + Stadt Köln (werden gefiltert)
                       r/Koeln, r/cologne, koeln0221, eigene Veedel-Blogs

Jede Quelle trägt einen ``scope`` – damit weiß die Relevanzprüfung, ob ein
Treffer „im Veedel", „im Bezirk" oder nur „irgendwo in Köln" passiert ist.
"""

from __future__ import annotations

from dataclasses import dataclass

from .places import BEZIRKE, Place

KSTA_FEED = "https://feed.ksta.de/feed/rss"
RUNDSCHAU_FEED = "https://feed.rundschau-online.de/feed/rss"
EXPRESS_FEED = "https://feed.express.de/feed/rss"


@dataclass
class SourceSpec:
    name: str
    kind: str                       # rss | html | reddit
    url: str = ""                   # für rss/html
    path: str = ""                  # für reddit, z. B. /r/Koeln/new
    group: str = "medien"           # medien | behoerden | foren | sport
    scope: str = "koeln"            # veedel | bezirk | koeln | region
    kind_of_item: str = "news"      # news | forum | polizei | presse
    optional: bool = False          # nur holen, wenn das Thema aktiviert ist
    category_hint: str = ""         # erzwingt eine Kategorie, z. B. "blaulicht"


# --------------------------------------------------------------------------
# Stadtweit relevante Quellen (werden später nach Veedel gefiltert)
# --------------------------------------------------------------------------
def stadtweite_quellen() -> list[SourceSpec]:
    return [
        SourceSpec("EXPRESS Köln", "rss", f"{EXPRESS_FEED}/koeln/index.rss",
                   group="medien", scope="koeln"),
        SourceSpec("Kölner Stadt-Anzeiger · Köln", "rss", f"{KSTA_FEED}/koeln/index.rss",
                   group="medien", scope="koeln", optional=True),
        SourceSpec("Kölnische Rundschau · Köln", "rss", f"{RUNDSCHAU_FEED}/koeln/index.rss",
                   group="medien", scope="koeln"),
        SourceSpec("koeln.de Lokalnews", "rss",
                   "https://www.koeln.de/feeds/lokalnews/anzahl=50/details=ja",
                   group="medien", scope="koeln"),
        SourceSpec("Polizei Köln (Presseportal NRW)", "rss",
                   "https://koeln.polizei.nrw/presse/pressemitteilungen/rss/all/14570/all/all/all",
                   group="behoerden", scope="koeln", kind_of_item="polizei",
                   category_hint="blaulicht"),
        SourceSpec("Stadt Köln · Pressemeldungen", "rss",
                   "https://www.stadt-koeln.de/externe-dienste/rss/pressemeldungen.xml",
                   group="behoerden", scope="koeln", kind_of_item="presse"),
    ]


# --------------------------------------------------------------------------
# Foren & Community (der explizit gewünschte Teil „relevante Foren für Köln")
# --------------------------------------------------------------------------
# Stadtteil-Slug -> [(Anzeigename, Feed-URL)]. WordPress-Blogs liefern ihr
# Feed immer unter /feed/, TYPO3-/Redaxo-Seiten meist unter /rss oder /feed.xml.
#
# Hier steht bewusst kein Eintrag: Der bekannte Ehrenfeld-Blog
# (ehrenfeldmich.wordpress.com/feed/) existiert zwar noch, hat aber seit
# Januar 2019 nichts mehr veröffentlicht – er würde nur Karteileichen liefern.
# Der Altersfilter im Aggregator fängt so etwas zusätzlich ab. Eigene, aktive
# Veedel-Blogs einfach hier eintragen, sie laufen dann als „foren".
VEEDEL_BLOGS: dict[str, list[tuple[str, str]]] = {}

FOREN: list[SourceSpec] = [
    SourceSpec("Reddit r/Koeln · neu", "reddit",
               path="/r/Koeln/new", group="foren", scope="koeln",
               kind_of_item="forum", category_hint="community"),
    SourceSpec("Reddit r/cologne · neu", "reddit",
               path="/r/cologne/new", group="foren", scope="koeln",
               kind_of_item="forum", category_hint="community"),
    SourceSpec("KOELN·0221 · Stadtportal & Community", "html",
               url="https://koeln0221.de/", group="foren", scope="koeln",
               kind_of_item="forum"),
]


# --------------------------------------------------------------------------
# Sport (eigene Kategorie, optional zuschaltbar)
# --------------------------------------------------------------------------
def sport_quellen() -> list[SourceSpec]:
    return [
        SourceSpec("KSTA · 1. FC Köln", "rss", f"{KSTA_FEED}/sport/1-fc-koeln/index.rss",
                   group="sport", scope="koeln", optional=True, category_hint="sport"),
        SourceSpec("Rundschau · Kölner Haie", "rss",
                   f"{RUNDSCHAU_FEED}/sport/koelner-haie/index.rss",
                   group="sport", scope="koeln", optional=True, category_hint="sport"),
        SourceSpec("Rundschau · Kölner Sport", "rss",
                   f"{RUNDSCHAU_FEED}/sport/koelner-sport/index.rss",
                   group="sport", scope="koeln", optional=True, category_hint="sport"),
    ]


# --------------------------------------------------------------------------
# Region (Bonn, Leverkusen, Rhein-Erft …) und fremde Städte
# --------------------------------------------------------------------------
REGION_QUELLEN = {
    "rhein-sieg-bonn": [
        ("KSTA · Rhein-Sieg & Bonn", f"{KSTA_FEED}/region/rhein-sieg-bonn/index.rss"),
        ("Rundschau · Bonn", f"{RUNDSCHAU_FEED}/region/bonn/index.rss"),
    ],
    "leverkusen": [
        ("KSTA · Leverkusen", f"{KSTA_FEED}/region/leverkusen/index.rss"),
    ],
    "rhein-erft": [
        ("KSTA · Rhein-Erft", f"{KSTA_FEED}/region/rhein-erft/index.rss"),
        ("Rundschau · Rhein-Erft", f"{RUNDSCHAU_FEED}/region/rhein-erft/index.rss"),
    ],
    "rhein-berg": [
        ("KSTA · Rhein-Berg", f"{KSTA_FEED}/region/rhein-berg/index.rss"),
        ("Rundschau · Rhein-Berg", f"{RUNDSCHAU_FEED}/region/rhein-berg/index.rss"),
    ],
    "oberberg": [
        ("KSTA · Oberberg", f"{KSTA_FEED}/region/oberberg/index.rss"),
        ("Rundschau · Oberberg", f"{RUNDSCHAU_FEED}/region/oberberg/index.rss"),
    ],
    "euskirchen-eifel": [
        ("KSTA · Euskirchen-Eifel", f"{KSTA_FEED}/region/euskirchen-eifel/index.rss"),
        ("Rundschau · Kreis Euskirchen", f"{RUNDSCHAU_FEED}/region/kreis-euskirchen/index.rss"),
    ],
}

# Reddit-Subreddits anderer Städte (nur Fallback, ohne kuratierte Lokalquellen)
STADT_SUBREDDITS = {
    "Berlin": ["berlin"], "Hamburg": ["hamburg"], "München": ["Muenchen", "munich"],
    "Frankfurt": ["Frankfurt", "frankfurt_main"], "Düsseldorf": ["Duesseldorf"],
    "Stuttgart": ["Stuttgart"], "Leipzig": ["leipzig"], "Dresden": ["Dresden"],
    "Hannover": ["hannover"], "Bremen": ["bremen"], "Essen": ["Essen"],
    "Dortmund": ["Dortmund"], "Bochum": ["Bochum"], "Wuppertal": ["Wuppertal"],
    "Aachen": ["Aachen"], "Mönchengladbach": ["moenchengladbach"],
    "Bonn": ["Bonn"], "Leverkusen": ["Leverkusen"],
}


# --------------------------------------------------------------------------
# Plan bauen
# --------------------------------------------------------------------------
def build_plan(place: Place, topics: set[str] | None = None) -> list[SourceSpec]:
    """Stellt die Quellenliste für einen Ort zusammen.

    ``topics`` kann ``"sport"``, ``"foren"``, ``"behoerden"`` enthalten;
    alles davon ist standardmäßig aktiv.
    """
    topics = topics or {"sport", "foren", "behoerden", "medien"}
    plan: list[SourceSpec] = []

    # ---- fremde Stadt (kein Köln-Profil) --------------------------------
    if place.kind in ("stadt", "unbekannt") and place.city != "Köln":
        city = place.city or place.name
        for sub in STADT_SUBREDDITS.get(city, [city.replace(" ", "").replace("ü", "ue")]):
            plan.append(SourceSpec(f"Reddit r/{sub} · neu", "reddit",
                                   path=f"/r/{sub}/new", group="foren", scope="koeln",
                                   kind_of_item="forum", category_hint="community"))
        return plan

    # ---- Region im KSTA-Verbreitungsgebiet ------------------------------
    if place.kind == "region" and place.region_slug:
        for name, url in REGION_QUELLEN.get(place.region_slug, []):
            plan.append(SourceSpec(name, "rss", url, group="medien", scope="region"))
        plan.append(SourceSpec(f"Reddit r/{place.name.replace(' ', '')} · neu", "reddit",
                               path=f"/r/{place.name.replace(' ', '')}/new", group="foren",
                               scope="region", kind_of_item="forum",
                               category_hint="community"))
        return plan

    # ---- Köln: Veedel- bzw. Bezirksfeeds --------------------------------
    bezirk_slug = place.bezirk_slug or BEZIRKE.get(place.bezirk or "", "koelner-innenstadt")

    if place.kind in ("stadtteil", "veedel"):
        # erst der exakte Stadtteilfeed. KSTA benennt Stadtteile, die wie ihr
        # Bezirk heißen, mit „-veedel" (Nippes -> nippes/nippes-veedel). Beide
        # Varianten werden parallel probiert; leere Feeds kosten nichts, weil
        # die Dedup doppelte Artikel wieder zusammenführt.
        for nr, s in enumerate(place.slugs[:2], start=1):
            name = f"KSTA · {place.name}" if nr == 1 else f"KSTA · {place.name} (Variante)"
            plan.append(SourceSpec(
                name, "rss",
                f"{KSTA_FEED}/koeln/{bezirk_slug}/{s}/index.rss",
                group="medien", scope="veedel",
            ))

    if place.bezirk:
        # … dann der Bezirksfeed (enthält alle Stadtteile des Bezirks)
        plan.append(SourceSpec(
            f"KSTA · Bezirk {place.bezirk}", "rss",
            f"{KSTA_FEED}/koeln/{bezirk_slug}/index.rss",
            group="medien", scope="bezirk",
        ))

    if place.kind == "stadt" or place.kind == "unbekannt":
        plan.append(SourceSpec("KSTA · Köln gesamt", "rss", f"{KSTA_FEED}/koeln/index.rss",
                               group="medien", scope="koeln"))

    # ---- Veedel-Blogs (Community) ---------------------------------------
    for s in place.slugs[:1]:
        for blog_name, blog_url in VEEDEL_BLOGS.get(s, []):
            plan.append(SourceSpec(blog_name, "rss", blog_url, group="foren",
                                   scope="veedel", kind_of_item="forum",
                                   category_hint="community"))

    # ---- stadtweite Medien + Behörden -----------------------------------
    for spec in stadtweite_quellen():
        if spec.group == "behoerden" and "behoerden" not in topics:
            continue
        if spec.group != "behoerden" and "medien" not in topics:
            continue
        if spec.optional and spec.group == "medien":
            continue                      # KSTA gesamt nur bei Bedarf (siehe oben)
        plan.append(spec)

    # ---- Sport ----------------------------------------------------------
    if "sport" in topics:
        plan.extend(sport_quellen())

    # ---- Foren ----------------------------------------------------------
    if "foren" in topics:
        plan.extend(FOREN)

    return plan


def plan_beschreibung(plan: list[SourceSpec]) -> dict:
    """Zählt die Quellen pro Gruppe – für die Statuszeile in der UI."""
    out: dict[str, int] = {}
    for spec in plan:
        out[spec.group] = out.get(spec.group, 0) + 1
    return out
