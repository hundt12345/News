# -*- coding: utf-8 -*-
"""Orchestrierung: Quellen parallel holen, bewerten, cachen, gruppieren.

Gegenüber der alten ``crawl_for_city``-Funktion:

* **parallel** statt sequenziell mit ``time.sleep(1)`` (vorher ~20 s Ladezeit)
* **Zwischenspeicher**: frische Ergebnisse 5 Minuten, bei Ausfall einer Quelle
  wird der letzte gute Stand gezeigt („stale") – so führt ein Reddit-403 nicht
  mehr zu einem leeren Stream
* **Diagnose** pro Quelle (HTTP-Code, Dauer, Fehler, Tipp) – sichtbar in der UI
* **Gruppierung** in Veedel / Bezirk / Köln / Foren und zusätzlich nach Themen
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone

from . import demo as demo_mod
from . import fetch as fetcher
from .fetch import Item, SourceResult
from .places import Place, benachbarte_stadtteile, resolve_place, slug
from .relevance import (
    KATEGORIEN,
    Matcher,
    categorize,
    dedupe,
    is_junk,
    match_place,
    sortieren,
    vielfalt,
)
from .sources import SourceSpec, build_plan

CACHE_DIR = os.environ.get("NEWS_CACHE_DIR", os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache"))
SOURCE_TTL = int(os.environ.get("NEWS_SOURCE_TTL", "300"))       # 5 Minuten
STALE_MAX_AGE = int(os.environ.get("NEWS_STALE_MAX_AGE", "86400"))  # 24 Stunden
MAX_WORKERS = int(os.environ.get("NEWS_MAX_WORKERS", "10"))

_lock = threading.Lock()
_disk_cache: dict[str, dict] = {}
_loaded = False


# --------------------------------------------------------------------------
# Zwischenspeicher (JSON auf der Platte, überlebt einen Render-Neustart nicht
# dauerhaft, verhindert aber leere Seiten bei kurzen Aussetzern)
# --------------------------------------------------------------------------
def _cache_path() -> str:
    return os.path.join(CACHE_DIR, "quellen.json")


def _load_cache() -> None:
    global _loaded
    with _lock:
        if _loaded:
            return
        try:
            with open(_cache_path(), encoding="utf-8") as fh:
                _disk_cache.update(json.load(fh))
        except Exception:                                  # noqa: BLE001
            pass
        _loaded = True


def _save_cache() -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        cutoff = time.time() - STALE_MAX_AGE
        data = {k: v for k, v in _disk_cache.items() if v.get("ts", 0) > cutoff}
        tmp = _cache_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, _cache_path())
    except Exception:                                      # noqa: BLE001
        pass


def _cache_get(key: str) -> dict | None:
    _load_cache()
    with _lock:
        return _disk_cache.get(key)


def _cache_put(key: str, items: list[Item], used: str) -> None:
    _load_cache()
    with _lock:
        _disk_cache[key] = {
            "ts": time.time(),
            "used": used,
            "items": [i.to_dict() for i in items],
        }
        if len(_disk_cache) % 10 == 0:
            _save_cache()


def _items_from_cache(entry: dict, name: str) -> list[Item]:
    out = []
    for raw in entry.get("items", []):
        pub = raw.get("published")
        try:
            published = datetime.fromisoformat(pub) if pub else None
        except ValueError:
            published = None
        out.append(Item(
            title=raw.get("title", ""), link=raw.get("link", ""),
            source=name, published=published, teaser=raw.get("teaser", ""),
            author=raw.get("author", ""), image=raw.get("image", ""),
            kind=raw.get("kind", "news"), url_slug=raw.get("url_slug", "")
            or fetcher._url_slug(raw.get("link", "")),
        ))
    return out


# --------------------------------------------------------------------------
# Eine Quelle holen (mit Cache)
# --------------------------------------------------------------------------
def _hole_quelle(spec: SourceSpec, force_refresh: bool = False,
                 demo: bool = False) -> SourceResult:
    """Holt eine Quelle – im Demo-Modus aus den gespeicherten Fixtures."""
    if demo:
        return demo_mod.demo_quelle(spec.name, spec.url, spec.path,
                                    spec.group, spec.kind_of_item)

    key = spec.url or f"reddit:{spec.path}"
    cached = _cache_get(key)
    age = time.time() - cached["ts"] if cached else None

    if cached and age is not None and age < SOURCE_TTL and not force_refresh:
        res = SourceResult(name=spec.name, url=spec.url or spec.path, ok=True,
                           items=_items_from_cache(cached, spec.name),
                           group=spec.group, used=f"Cache ({int(age)} s alt)")
        return res

    if spec.kind == "reddit":
        res = fetcher.fetch_reddit(spec.name, spec.path, group=spec.group)
    elif spec.kind == "html":
        res = fetcher.fetch_html(spec.name, spec.url, group=spec.group)
        if res.ok and not res.items:
            discovered = fetcher.discover_feed_url(spec.url)
            if discovered:
                alt = fetcher.fetch_rss(spec.name, discovered,
                                        kind=spec.kind_of_item, group=spec.group)
                if alt.ok and alt.items:
                    res = alt
    else:
        res = fetcher.fetch_rss(spec.name, spec.url, kind=spec.kind_of_item,
                                group=spec.group)

    if res.ok and res.items:
        _cache_put(key, res.items, res.used)
    elif cached and age is not None and age < STALE_MAX_AGE:
        # Quelle gerade nicht erreichbar -> letzten guten Stand zeigen
        fallback = SourceResult(
            name=spec.name, url=spec.url or spec.path, ok=False,
            items=_items_from_cache(cached, spec.name), group=spec.group,
            error=res.error, hint=res.hint, seconds=res.seconds,
            used=f"Letzter guter Stand ({int(age / 60)} Min. alt)",
        )
        return fallback
    return res


# --------------------------------------------------------------------------
# Ergebnis
# --------------------------------------------------------------------------
@dataclass
class Abschnitt:
    key: str
    label: str
    hinweis: str
    items: list[Item]


def _abschnitte(items: list[Item], place: Place) -> list[Abschnitt]:
    """Baut die Sicht „Nach Ort": Veedel -> Bezirk -> Stadt.

    Welche Abschnitte es gibt, hängt von der Anfrage ab: Bei einem Stadtteil
    steht das Veedel immer zuerst (auch wenn es leer ist – dann erklärt der
    Hinweistext, warum). Bei einer Stadt-Anfrage gibt es nur eine Liste.
    """
    veedel = [i for i in items if i.scope == "veedel"]
    bezirk = [i for i in items if i.scope in ("bezirk", "region")]
    stadt = [i for i in items if i.scope == "koeln"]

    if place.kind in ("stadtteil", "veedel"):
        out = [Abschnitt(
            "veedel", place.name,
            "Meldungen mit direktem Bezug zu diesem Veedel – geprüft über "
            "URL-Ablage der Redaktion, Ortsnamen und Straßennamen",
            sortieren(veedel))]
        if bezirk:
            out.append(Abschnitt(
                "bezirk", f"Bezirk {place.bezirk}",
                "Nachbarveedel im selben Stadtbezirk", sortieren(bezirk)))
        if stadt:
            out.append(Abschnitt(
                "koeln", "Köln gesamt",
                "Stadtweite Meldungen ohne Veedel-Bezug", sortieren(stadt)))
        return out

    if place.kind == "bezirk":
        out = [Abschnitt(
            "veedel", place.headline,
            f"Meldungen aus den {len(place.stadtteile)} Stadtteilen des Bezirks",
            sortieren(veedel + bezirk))]
        if stadt:
            out.append(Abschnitt("koeln", "Köln gesamt",
                                 "Stadtweite Meldungen ohne Veedel-Bezug",
                                 sortieren(stadt)))
        return out

    if place.kind == "region":
        return [Abschnitt("koeln", f"Region {place.name}",
                          "Meldungen aus der Region",
                          sortieren(veedel + bezirk + stadt))]

    # ganze Stadt / unbekannter Begriff
    return [Abschnitt("koeln", place.headline,
                      "Alle Meldungen, sortiert nach Alter und Quelle",
                      sortieren(veedel + bezirk + stadt))]


def _nach_kategorie(items: list[Item]) -> dict[str, list[Item]]:
    out: dict[str, list[Item]] = {}
    for it in items:
        out.setdefault(it.category, []).append(it)
    for kat in out:
        out[kat] = sortieren(out[kat])
    return out


# --------------------------------------------------------------------------
# Hauptfunktion
# --------------------------------------------------------------------------
# Älter als das darf eine Meldung nicht sein – sonst liefern eingeschlafene
# Blogs oder ein hängengebliebener Cache irgendwann Karteileichen.
MAX_ALTER_TAGE = int(os.environ.get("NEWS_MAX_ALTER_TAGE", "60"))


def _zu_alt(item: Item, tage: int = MAX_ALTER_TAGE) -> bool:
    if item.published is None:
        return False
    return (datetime.now(timezone.utc) - item.published).days > tage


def aggregate_news(query: str = "Köln",
                   topics: set[str] | None = None,
                   force_refresh: bool = False,
                   max_pro_quelle: int = 10,
                   max_stadtweit: int = 25,
                   demo: bool = False,
                   ) -> dict:
    """Holt und gruppiert die Nachrichten für ``query``."""
    started = time.time()
    place = resolve_place(query)
    topics = topics or {"medien", "behoerden", "sport", "foren"}
    matcher = Matcher.build(place)
    plan = build_plan(place, topics)

    # ---- parallel holen -------------------------------------------------
    # Die Ergebnisse werden in Plan-Reihenfolge ausgewertet, damit das
    # Ergebnis unabhängig von der Antwortgeschwindigkeit der Server ist
    # (wichtig für Dedup und für reproduzierbare Tests).
    paarweise: list[tuple[SourceSpec | None, SourceResult]] = []
    if plan:
        fertig: dict[int, SourceResult] = {}
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(plan))) as pool:
            futures = {pool.submit(_hole_quelle, spec, force_refresh, demo): spec
                       for spec in plan}
            for fut in as_completed(futures):
                spec = futures[fut]
                try:
                    fertig[id(spec)] = fut.result()
                except Exception as exc:                     # noqa: BLE001
                    fertig[id(spec)] = SourceResult(
                        name=spec.name, url=spec.url or spec.path, ok=False,
                        error=f"{type(exc).__name__}: {exc}", group=spec.group)
        paarweise = [(spec, fertig[id(spec)]) for spec in plan if id(spec) in fertig]

    results = [res for _, res in paarweise]

    # ---- bewerten -------------------------------------------------------
    keep: list[Item] = []
    raw_count = 0
    alt_count = 0
    for spec, res in paarweise:
        source_scope = spec.scope if spec else "koeln"
        forced_cat = spec.category_hint if spec else ""
        raw_count += len(res.items)
        for item in res.items:
            item.kind = item.kind or (spec.kind_of_item if spec else "news")
            if _zu_alt(item):
                alt_count += 1
                continue
            if is_junk(item):
                continue
            score, scope, ev = match_place(
                item, matcher, source_scope,
                spec.kind_of_item if spec else "")
            item.score, item.scope, item.evidence = score, scope, ev
            item.category = categorize(item, forced_cat)

            # Was darf bleiben?
            # match_place meldet eine Ablehnung mit Punktzahl 0 *und* Beleg
            # („handelt von Ehrenfeld", „spielt außerhalb Kölns"). Ohne Beleg
            # heißt 0 nur: es war nichts zu finden.
            if score <= 0 and ev:
                continue

            if source_scope in ("veedel", "bezirk", "region"):
                # Stadtteil- und Bezirksfeeds werden von den Redaktionen von
                # Hand abgelegt. Ein Artikel ohne Ortsfund im Text gehört
                # deshalb trotzdem in diesen Abschnitt.
                if not scope:
                    scope = item.scope = source_scope
                item.score = max(item.score, 30.0)
                keep.append(item)
            elif item.kind == "forum":
                # Forum-Posts nennen selten den Ort; ein Post im Köln-Subreddit
                # ist aber mindestens stadtweit relevant.
                item.score = max(item.score, 10.0)
                item.scope = item.scope or "koeln"
                item.evidence = item.evidence or ["aus dem Köln-Forum"]
                keep.append(item)
            elif item.score >= 12:
                keep.append(item)

    keep = dedupe(keep)
    keep = vielfalt(keep, max_pro_quelle=max_pro_quelle)

    # stadtweite Meldungen begrenzen, damit das Veedel dominiert
    stadtweit = [i for i in keep if i.scope == "koeln"]
    if len(stadtweit) > max_stadtweit:
        drop = {id(i) for i in stadtweit[max_stadtweit:]}
        keep = [i for i in keep if id(i) not in drop]

    abschnitte = _abschnitte(keep, place)
    kategorien = _nach_kategorie(keep)

    # Themenchips: nach Menge sortiert, damit das Wichtigste zuerst steht
    top_themen = {
        kat: len(kategorien[kat])
        for kat in sorted(kategorien, key=lambda k: -len(kategorien[k]))
    }

    ok = sum(1 for r in results if r.ok)
    fehler = [r for r in results if not r.ok]

    return {
        "place": {
            "query": place.query, "name": place.name, "kind": place.kind,
            "label": place.label, "headline": place.headline,
            "city": place.city, "bezirk": place.bezirk,
            "stadtteile": place.stadtteile,
            "nachbarn": benachbarte_stadtteile(place),
            "slug": slug(place.name),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "duration_s": round(time.time() - started, 2),
        "demo": demo,
        "sections": [
            {"key": a.key, "label": a.label, "hinweis": a.hinweis,
             "artikel": [i.to_dict() for i in a.items]}
            for a in abschnitte
        ],
        "categories": {
            kat: {
                "label": KATEGORIEN[kat]["label"],
                "icon": KATEGORIEN[kat]["icon"],
                "info": KATEGORIEN[kat]["info"],
                "artikel": [i.to_dict() for i in kategorien.get(kat, [])],
            }
            for kat in KATEGORIEN if kategorien.get(kat)
        },
        "topics": {
            kat: len(kategorien.get(kat, [])) for kat in KATEGORIEN
            if kategorien.get(kat)
        },
        "top_themen": top_themen,
        "sources": [r.to_dict() for r in
                    sorted(results, key=lambda r: (r.ok, r.group, r.name))],
        "stats": {
            "quellen_gesamt": len(results),
            "quellen_ok": ok,
            "quellen_fehler": len(fehler),
            "artikel_roh": raw_count,
            "artikel_zu_alt": alt_count,
            "artikel_behalten": len(keep),
            "veedel_treffer": sum(1 for i in keep if i.scope == "veedel"),
            "bezirk_treffer": sum(1 for i in keep if i.scope == "bezirk"),
            "aeltester_artikel": min(
                (i.published.isoformat() for i in keep if i.published), default=None),
            "neuester_artikel": max(
                (i.published.isoformat() for i in keep if i.published), default=None),
        },
        "warnungen": ([demo_mod.HINWEIS] if demo else [])
                     + _warnungen(place, results, keep),
    }


def _warnungen(place: Place, results: list[SourceResult], keep: list[Item]) -> list[str]:
    out: list[str] = []
    if place.kind == "unbekannt":
        out.append(
            f"„{place.query}“ wurde nicht als Kölner Stadtteil, Bezirk oder Veedel "
            "erkannt – gezeigt wird ganz Köln. Tipp: „Ehrenfeld“, „Bezirk Nippes“ "
            "oder „Südstadt“ eingeben.")
    reddit = [r for r in results if r.group == "foren" and "Reddit" in r.name]
    if reddit and all(not r.ok for r in reddit):
        out.append(
            "Reddit ist gerade nicht erreichbar (Server-IPs werden oft blockiert). "
            "Die lokalen Redaktionen liefern unabhängig davon weiter. "
            "Für dauerhaften Reddit-Zugang REDDIT_CLIENT_ID/SECRET setzen.")
    if not any(i.scope == "veedel" for i in keep):
        if place.kind in ("stadtteil", "veedel"):
            out.append(
                f"Keine Meldung nennt {place.name} ausdrücklich – gezeigt wird der "
                f"Bezirk {place.bezirk}. Lokalredaktionen berichten nicht täglich "
                "über jedes Veedel.")
    if not keep:
        out.append(
            "Keine Treffer: entweder sind die Quellen gerade nicht erreichbar "
            "(siehe Quellen-Protokoll unten) oder der Ort wurde nicht erkannt.")
    return out


# --------------------------------------------------------------------------
# Rückwärtskompatibilität: die alte Schnittstelle bleibt erhalten
# --------------------------------------------------------------------------
def crawl_for_city(city: str, max_items: int = 30, demo: bool = False) -> dict:
    """Wie früher, aber mit korrekter Ortsauflösung.

    Liefert ``{"stream": [...], "summary": {...}}`` mit dict-Einträgen,
    damit alter Code weiterläuft.
    """
    data = aggregate_news(city, demo=demo)
    stream: list[dict] = []
    for section in data["sections"]:
        stream.extend(section["artikel"])
    stream = stream[:max_items]
    summary = {kat: info["artikel"][:5] for kat, info in data["categories"].items()}
    return {"stream": stream, "summary": summary, "raw": data}
