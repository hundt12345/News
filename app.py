# -*- coding: utf-8 -*-
"""Lokal-Radar – Flask-Oberfläche für den News-Aggregator.

Routen
------
``/``             Seite (serverseitig gerendert, funktioniert auch ohne JS)
``/api/news``     JSON oder gerendertes HTML-Fragment (für „Aktualisieren")
``/api/orte``     Alle Stadtteile/Veedel für die Autovervollständigung
``/health``       Liveness-Probe für Render

Start:  ``python app.py``  ->  http://127.0.0.1:5000
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request

from news import fetch as fetcher
from news.aggregator import aggregate_news
from news.places import BEZIRKE, ortsliste, resolve_place
from news.relevance import KATEGORIEN
from news.weather import get_weather

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

# --------------------------------------------------------------------------
# Konfiguration über Umgebungsvariablen
# --------------------------------------------------------------------------
fetcher.REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
fetcher.REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
fetcher.REDDIT_MIRROR = os.environ.get("REDDIT_MIRROR", "")

ALLE_THEMEN = {"medien", "behoerden", "sport", "foren"}
THEMEN_LABEL = {
    "medien": "📰 Redaktionen",
    "behoerden": "🚨 Polizei & Stadt",
    "sport": "⚽ Sport",
    "foren": "💬 Foren & Community",
}


# --------------------------------------------------------------------------
# Jinja-Filter
# --------------------------------------------------------------------------
@app.template_filter("relativ")
def relativ(iso: str | None) -> str:
    """ISO-Zeit -> „vor 12 Min." (deutsch, ohne Zusatzbibliothek)."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    minuten = int(delta.total_seconds() // 60)
    if minuten < 1:
        return "gerade eben"
    if minuten < 60:
        return f"vor {minuten} Min."
    stunden = minuten // 60
    if stunden < 24:
        return f"vor {stunden} Std."
    tage = stunden // 24
    if tage == 1:
        return "gestern"
    if tage < 7:
        return f"vor {tage} Tagen"
    return dt.strftime("%d.%m.%Y")


@app.template_filter("zeitpunkt")
def zeitpunkt(iso: str | None) -> str:
    if not iso:
        return "ohne Zeitstempel"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    return dt.astimezone().strftime("%d.%m.%Y, %H:%M")


@app.context_processor
def globals_fuer_templates():
    return {"KATEGORIEN": KATEGORIEN, "THEMEN_LABEL": THEMEN_LABEL}


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------
def _themen_aus_request() -> set[str]:
    raw = request.values.get("themen", "")
    if not raw:
        return set(ALLE_THEMEN)
    gewaehlt = {t.strip() for t in raw.replace(";", ",").split(",") if t.strip()}
    return gewaehlt & ALLE_THEMEN or set(ALLE_THEMEN)


def _wetter_ort(ort: str) -> str:
    """Für Wetter immer die Stadt, nicht das Veedel (Geocoding wäre ungenau)."""
    place = resolve_place(ort)
    if place.kind in ("stadtteil", "bezirk", "veedel", "stadt"):
        return place.city or "Köln"
    return place.name or ort


def _demo_modus() -> bool:
    """Demo-Modus: gespeicherte Original-Feeds statt Live-Abruf."""
    return (request.args.get("demo") == "1"
            or os.environ.get("NEWS_DEMO", "0") == "1")


def _daten_holen(ort: str, themen: set[str], refresh: bool,
                 demo: bool = False) -> dict:
    """News und Wetter parallel holen – Wetter darf die Seite nie ausbremsen."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        news_fut = pool.submit(lambda: aggregate_news(
            ort, themen, force_refresh=refresh, demo=demo))
        wetter_fut = pool.submit(get_weather, _wetter_ort(ort)) if not demo else \
            pool.submit(lambda: {"ort": ort, "temp": 14, "text": "Teilweise bewölkt",
                                 "icon": "⛅", "min": 9, "max": 16, "wind": 12,
                                 "quelle": "Demo-Daten"})
        try:
            daten = news_fut.result()
        except Exception as exc:                           # noqa: BLE001
            daten = {
                "place": {"query": ort, "name": ort, "kind": "unbekannt",
                          "label": ort, "headline": ort, "city": ort,
                          "bezirk": None, "stadtteile": [], "nachbarn": [],
                          "slug": ort},
                "sections": [], "categories": {}, "topics": {}, "sources": [],
                "stats": {"quellen_gesamt": 0, "quellen_ok": 0, "quellen_fehler": 0,
                          "artikel_roh": 0, "artikel_behalten": 0,
                          "veedel_treffer": 0, "bezirk_treffer": 0},
                "warnungen": [f"Die Abfrage ist fehlgeschlagen: {exc}"],
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "duration_s": 0.0,
            }
        try:
            wetter = wetter_fut.result(timeout=12)
        except Exception:                                  # noqa: BLE001
            wetter = None
    daten["wetter"] = wetter
    return daten


# --------------------------------------------------------------------------
# Routen
# --------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def index():
    ort = (request.args.get("ort") or "").strip() or "Köln"
    themen = _themen_aus_request()
    daten = _daten_holen(ort, themen,
                         refresh=request.args.get("refresh") == "1",
                         demo=_demo_modus())

    return render_template(
        "index.html",
        daten=daten,
        ort=ort,
        place=resolve_place(ort),
        themen=sorted(themen),
        alle_themen=sorted(ALLE_THEMEN),
        orte=ortsliste(),
        bezirke=BEZIRKE,
    )


@app.route("/api/news", methods=["GET"])
def api_news():
    ort = (request.args.get("ort") or "Köln").strip()
    themen = _themen_aus_request()
    refresh = request.args.get("refresh") == "1"
    fmt = request.args.get("fmt", "json")

    daten = _daten_holen(ort, themen, refresh, _demo_modus())
    daten["themen"] = sorted(themen)

    if fmt == "html":
        daten["html"] = render_template("partials/results.html", daten=daten,
                                        ort=ort, place=resolve_place(ort),
                                        themen=sorted(themen))
        resp = jsonify(daten)
    else:
        resp = jsonify(daten)

    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@app.route("/api/orte", methods=["GET"])
def api_orte():
    q = (request.args.get("q") or "").strip().lower()
    orte = ortsliste()
    if q:
        orte = [o for o in orte if q in o["name"].lower()][:25]
    return jsonify({"orte": orte, "bezirke": BEZIRKE})


@app.route("/api/quellen", methods=["GET"])
def api_quellen():
    """Welche Quellen für einen Ort geplant wären – praktisch zum Debuggen."""
    from news.sources import build_plan
    place = resolve_place((request.args.get("ort") or "Köln").strip())
    plan = build_plan(place, _themen_aus_request())
    return jsonify({
        "ort": place.label,
        "quellen": [{"name": s.name, "gruppe": s.group, "typ": s.kind,
                     "url": s.url or f"reddit{s.path}", "scope": s.scope}
                    for s in plan],
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok", "zeit": datetime.now(timezone.utc).isoformat()})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)
