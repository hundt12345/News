# -*- coding: utf-8 -*-
"""Offline-Tests für den Lokal-Radar.

Kein Netzwerk nötig: ``_hole_quelle`` wird durch einen Double ersetzt, der
**echte** Feed-Inhalte aus ``tests/fixtures/`` liefert (am 13.10.2026 von
ksta.de, express.de, koeln.polizei.nrw, stadt-koeln.de und reddit.com gezogen).

Ausführen:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from news import aggregator                                     # noqa: E402
from news.fetch import Item, SourceResult, parse_feed           # noqa: E402
from news.places import resolve_place, slug, translit, ortsliste  # noqa: E402
from news.relevance import (Matcher, categorize, dedupe,        # noqa: E402
                            is_junk, match_place, vielfalt)
from news.sources import build_plan                             # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

def fixture(name: str) -> bytes:
    """Rohinhalt einer gespeicherten Feed-Datei."""
    with open(os.path.join(FIXTURES, name), "rb") as fh:
        return fh.read()


def artikel(daten: dict, abschnitt: str) -> list[dict]:
    for sec in daten["sections"]:
        if sec["key"] == abschnitt:
            return sec["artikel"]
    return []


def titel(daten: dict, abschnitt: str) -> list[str]:
    return [i["title"] for i in artikel(daten, abschnitt)]


# ==========================================================================
class TestOrtsaufloesung(unittest.TestCase):
    """Früher: jede Eingabe landete auf den Deutz-Feeds."""

    def test_stadtteil(self):
        p = resolve_place("Ehrenfeld")
        self.assertEqual(p.kind, "stadtteil")
        self.assertEqual(p.bezirk, "Ehrenfeld")
        self.assertEqual(p.bezirk_slug, "ehrenfeld")
        self.assertIn("ehrenfeld", p.slugs)

    def test_stadtteil_mit_stadt_praefix(self):
        for eingabe in ("Köln-Nippes", "Köln Nippes", "Nippes", "koeln-nippes"):
            p = resolve_place(eingabe)
            self.assertEqual(p.name, "Nippes", eingabe)
            self.assertEqual(p.bezirk, "Nippes", eingabe)

    def test_umlaut_und_sonderzeichen(self):
        self.assertEqual(slug("Bocklemünd/Mengenich"), "bocklemuend-mengenich")
        self.assertEqual(slug("Köln-Südstadt"), "koeln-suedstadt")
        self.assertEqual(translit("Müngersdorf"), "muengersdorf")
        p = resolve_place("Bilderstöckchen")
        self.assertEqual(p.name, "Bilderstöckchen")
        self.assertEqual(p.bezirk, "Nippes")
        self.assertIn("bilderstoeckchen", p.slugs)

    def test_veedel_statt_offiziellem_stadtteil(self):
        p = resolve_place("Südstadt")
        self.assertEqual(p.kind, "veedel")
        self.assertEqual(p.stadtteile, ["Neustadt-Süd"])
        self.assertEqual(p.bezirk, "Innenstadt")
        self.assertIn("severinstr", " ".join(p.keywords))

        p = resolve_place("Belgisches Viertel")
        self.assertEqual(p.stadtteile, ["Neustadt-Nord"])

    def test_bezirk(self):
        p = resolve_place("Bezirk Kalk")
        self.assertEqual(p.kind, "bezirk")
        self.assertEqual(len(p.stadtteile), 9)
        self.assertIn("Vingst", p.stadtteile)

    def test_gleichnamiger_stadtteil_bekommt_veedel_slug(self):
        # Nippes ist Bezirk *und* Stadtteil -> KSTA nutzt nippes/nippes-veedel
        p = resolve_place("Nippes")
        self.assertEqual(p.slugs[0], "nippes-veedel")
        self.assertIn("nippes", p.slugs)
        # Deutz liegt im Bezirk Innenstadt -> koelner-innenstadt/deutz (verifiziert)
        d = resolve_place("Deutz")
        self.assertEqual(d.bezirk_slug, "koelner-innenstadt")
        self.assertIn("deutz", d.slugs)

    def test_region_und_andere_stadt(self):
        self.assertEqual(resolve_place("Bonn").kind, "region")
        self.assertEqual(resolve_place("Leverkusen").kind, "region")
        self.assertEqual(resolve_place("Berlin").kind, "stadt")
        self.assertEqual(resolve_place("Berlin").city, "Berlin")

    def test_unbekannt_bleibt_bei_koeln(self):
        p = resolve_place("asdfqwertz")
        self.assertEqual(p.kind, "unbekannt")
        self.assertEqual(p.city, "Köln", "unbekannte Eingabe darf nicht als fremde Stadt gelten")

    def test_alle_86_stadtteile_bekannt(self):
        orte = [o for o in ortsliste() if o["typ"] == "Stadtteil"]
        self.assertEqual(len(orte), 86)
        for o in orte:
            self.assertEqual(resolve_place(o["name"]).kind, "stadtteil", o["name"])


# ==========================================================================
class TestFeedParser(unittest.TestCase):

    def test_rss_mit_datum_und_slug(self):
        items = parse_feed(fixture("ksta_nippes_bezirk.xml"), "KSTA", "")
        self.assertEqual(len(items), 7)
        erster = items[0]
        self.assertIn("Etat-Kürzungen", erster.title)
        self.assertIsNotNone(erster.published)
        self.assertIsNotNone(erster.published.tzinfo)
        self.assertEqual(erster.url_slug.split("/")[2], "nippes-veedel")
        self.assertTrue(erster.teaser)

    def test_atom_reddit(self):
        items = parse_feed(fixture("reddit_koeln.atom"), "r/Koeln", "", kind="forum")
        self.assertEqual(len(items), 3)
        self.assertTrue(all(i.kind == "forum" for i in items))
        self.assertTrue(all(i.link.startswith("https://www.reddit.com/r/Koeln/") for i in items))
        self.assertTrue(items[0].teaser)

    def test_polizei_feed(self):
        items = parse_feed(fixture("polizei_koeln.xml"), "Polizei Köln", "", kind="polizei")
        self.assertEqual(len(items), 4)


# ==========================================================================
class TestRelevanz(unittest.TestCase):
    """Kern des Bugfixes: kein Stadtteil darf fremde Artikel bekommen."""

    def setUp(self):
        self.nippes = resolve_place("Nippes")
        self.matcher = Matcher.build(self.nippes)

    def _items(self, datei, name, slug_basis=""):
        return parse_feed(fixture(datei), name, slug_basis)

    def test_url_position_entscheidet(self):
        """…/koeln/nippes/weidenpesch/… ist Bezirk, nicht Veedel Nippes."""
        items = self._items("ksta_nippes_bezirk.xml", "KSTA")
        for it in items:
            score, scope, ev = match_place(it, self.matcher)
            if "/weidenpesch/" in it.link or "/niehl/" in it.link \
                    or "/bilderstoeckchen/" in it.link:
                self.assertEqual(scope, "bezirk", it.title)
                self.assertLessEqual(score, 55)
            else:
                self.assertEqual(scope, "veedel", it.title)
                self.assertGreaterEqual(score, 90)

    def test_fremde_stadtteile_fliegen_raus(self):
        """Deutzer Artikel tauchen bei einer Nippes-Suche nicht als Veedel-Treffer auf."""
        deutz = self._items("ksta_deutz_stadtteil.xml", "KSTA Deutz")
        for it in deutz:
            score, scope, _ = match_place(it, self.matcher)
            self.assertNotEqual(scope, "veedel", it.title)

    def test_landmark_treffer(self):
        it = Item(title="Anwohner ärgern sich über Lärm",
                  link="https://www.ksta.de/koeln/x/y/z-1",
                  source="Test", teaser="Auf der Neusser Straße wird es nachts laut.")
        score, scope, ev = match_place(it, self.matcher)
        self.assertEqual(scope, "veedel")
        self.assertTrue(any("neusser" in e.lower() for e in ev), ev)

    def test_mehrdeutiger_name_braucht_koeln_bezug(self):
        kalk = Matcher.build(resolve_place("Kalk"))
        ohne_koeln = Item(title="Kalk wird teurer", link="https://x.de/a/b/c",
                          source="Test", teaser="Chemieindustrie meldet Engpass.")
        mit_koeln = Item(title="Kalk wird teurer", link="https://x.de/a/b/c",
                         source="Test", teaser="Mieten in Köln steigen weiter.")
        self.assertEqual(match_place(ohne_koeln, kalk)[1], "")
        self.assertEqual(match_place(mit_koeln, kalk)[1], "veedel")

    def test_express_stadtteile_werden_erkannt(self):
        items = self._items("express_koeln.xml", "EXPRESS")
        zollstock = Matcher.build(resolve_place("Zollstock"))
        muellheim = Matcher.build(resolve_place("Mülheim"))
        chorweiler = Matcher.build(resolve_place("Chorweiler"))

        nach_ort = {i.title: match_place(i, zollstock)[1] for i in items}
        zollstock_treffer = [t for t, s in nach_ort.items() if s == "veedel"]
        self.assertTrue(any("Zollstock" in t for t in zollstock_treffer))

        self.assertTrue(any(match_place(i, muellheim)[1] == "veedel"
                            for i in items if "Kiosk" in i.title))
        self.assertTrue(any(match_place(i, chorweiler)[1] == "veedel"
                            for i in items if "Chorweiler" in i.title))

    def test_junk_filter(self):
        items = self._items("express_koeln.xml", "EXPRESS")
        junk = [i for i in items if is_junk(i)]
        self.assertTrue(any("Skechers" in i.title for i in junk))
        self.assertFalse(any("Kiosk" in i.title for i in junk))

    def test_leverkusen_ohne_koeln_bezug_bekommt_keinen_score(self):
        polizei = self._items("polizei_koeln.xml", "Polizei Köln")
        matcher = Matcher.build(resolve_place("Nippes"))
        for it in polizei:
            if "Leverkusenerin" in it.title:
                score, scope, _ = match_place(it, matcher)
                self.assertEqual(scope, "", "Leverkusen hat in einem Kölner Veedel nichts zu suchen")
                self.assertEqual(score, 0.0)

    def test_kategorien(self):
        polizei = self._items("polizei_koeln.xml", "Polizei Köln")
        kat = {i.title: categorize(i, "blaulicht") for i in polizei}
        self.assertEqual(set(kat.values()), {"blaulicht"})

        nippes = self._items("ksta_nippes_bezirk.xml", "KSTA")
        fuer = {i.title: categorize(i) for i in nippes}
        self.assertEqual(
            fuer["Radverkehr: Erste „Protected Bike Lane“ im Bezirk Nippes entsteht an Scheibenstraße"],
            "verkehr")
        self.assertEqual(
            fuer["Grün, Büze und Soziales: Nippes protestiert gegen Etat-Kürzungen"],
            "politik")

        deutz = self._items("ksta_deutz_stadtteil.xml", "KSTA")
        self.assertEqual(categorize([i for i in deutz if "Rosenmontag" in i.title][0]),
                         "kultur")

    def test_dedupe_ueber_quellen(self):
        """KSTA und EXPRESS liefern dieselbe Meldung mit anderer Dachzeile."""
        a = self._items("ksta_nippes_bezirk.xml", "KSTA · Nippes")
        b = self._items("express_koeln.xml", "EXPRESS Köln")
        merged = dedupe(a + b)
        butlers = [i for i in merged if "Butlers" in i.title]
        self.assertEqual(len(butlers), 1, [i.title for i in butlers])
        self.assertIn("EXPRESS Köln", butlers[0].also_from)

    def test_dedupe_trennt_unterschiedliche_artikel(self):
        a = self._items("ksta_deutz_stadtteil.xml", "KSTA · Deutz")
        b = self._items("express_koeln.xml", "EXPRESS Köln")
        merged = dedupe(a + b)
        wiesn = [i for i in merged if "Royal Wiesn" in i.title]
        self.assertEqual(len(wiesn), 2, "zwei verschiedene Artikel zum selben Event")

    def test_vielfalt_statt_einer_quelle(self):
        items = []
        for n in range(12):
            items.append(Item(title=f"Meldung {n} aus dem Veedel", link=f"https://a/{n}",
                              source="KSTA", score=90, scope="veedel"))
        for n in range(4):
            items.append(Item(title=f"Meldung P{n}", link=f"https://p/{n}",
                              source="Polizei", score=80, scope="veedel"))
        gemischt = vielfalt(items, max_pro_quelle=8)
        self.assertIn("Polizei", [i.source for i in gemischt[:4]])


# ==========================================================================
class TestQuellenplan(unittest.TestCase):

    def test_stadtteil_bekommt_eigenen_feed(self):
        plan = build_plan(resolve_place("Ehrenfeld"))
        urls = [s.url for s in plan]
        self.assertIn("https://feed.ksta.de/feed/rss/koeln/ehrenfeld/ehrenfeld/index.rss", urls)
        self.assertIn("https://feed.ksta.de/feed/rss/koeln/ehrenfeld/index.rss", urls)

    def test_deutz_bekommt_innenstadt_pfad(self):
        urls = [s.url for s in build_plan(resolve_place("Deutz"))]
        self.assertIn(
            "https://feed.ksta.de/feed/rss/koeln/koelner-innenstadt/deutz/index.rss", urls)

    def test_veedel_nutzt_offiziellen_stadtteil(self):
        urls = [s.url for s in build_plan(resolve_place("Südstadt"))]
        self.assertTrue(any("koelner-innenstadt/neustadt-sued" in u for u in urls), urls)

    def test_foren_sind_dabei(self):
        plan = build_plan(resolve_place("Nippes"))
        pfade = [s.path for s in plan if s.kind == "reddit"]
        self.assertIn("/r/Koeln/new", pfade)
        self.assertIn("/r/cologne/new", pfade)

    def test_themen_abschaltbar(self):
        plan = build_plan(resolve_place("Nippes"), {"medien"})
        self.assertFalse([s for s in plan if s.group in ("foren", "sport", "behoerden")])

    def test_region_bekommt_regionsfeeds(self):
        urls = [s.url for s in build_plan(resolve_place("Bonn"))]
        self.assertTrue(any("region/rhein-sieg-bonn" in u for u in urls), urls)

    def test_andere_stadt_bekommt_reddit(self):
        plan = build_plan(resolve_place("Berlin"))
        self.assertTrue(any(s.path == "/r/berlin/new" for s in plan), plan)


# ==========================================================================
class TestEndToEnd(unittest.TestCase):
    """Kompletter Durchlauf mit Fixtures statt Netzwerk."""

    def test_nippes(self):
        daten = aggregator.aggregate_news("Nippes", demo=True)
        self.assertGreater(daten["stats"]["artikel_behalten"], 0)

        veedel = titel(daten, "veedel")
        self.assertTrue(any("Etat-Kürzungen" in t for t in veedel), veedel)
        self.assertTrue(any("Butlers" in t for t in veedel), veedel)
        # kein Deutz, kein Leverkusen, kein Shopping
        alle = [i["title"] for s in daten["sections"] for i in s["artikel"]]
        self.assertFalse(any("Deutz" in t and "Mensa" in t for t in alle), alle)
        self.assertFalse(any("Skechers" in t for t in alle), alle)
        self.assertFalse(any("Leverkusenerin" in t for t in alle), alle)

        # Weidenpesch/Niehl/Bilderstöckchen = Bezirk, nicht Veedel
        bezirk = titel(daten, "bezirk")
        self.assertTrue(any("Bilderstöckchen" in t for t in bezirk), bezirk)
        self.assertFalse(any("Bilderstöckchen" in t for t in veedel), veedel)

        # Kategorien vorhanden und Reddit als Community einsortiert
        self.assertIn("community", daten["categories"])
        self.assertTrue(all(i["category"] == "community"
                            for i in daten["categories"]["community"]["artikel"]))

        # Foren ohne Ortsbezug landen in „Köln gesamt", nicht im Veedel
        self.assertTrue(any("KVB" in t for t in titel(daten, "koeln")))

    def test_bilderstoeckchen_bekommt_nur_sein_veedel(self):
        daten = aggregator.aggregate_news("Bilderstöckchen", demo=True)
        veedel = titel(daten, "veedel")
        self.assertTrue(any("Bilderstöckchen" in t for t in veedel), veedel)
        # der Polizei-Artikel zu Bilderstöckchen wird über den Text erkannt
        self.assertTrue(any("Einbrecher" in t for t in veedel), veedel)
        self.assertFalse(any("Butlers" in t for t in veedel), veedel)

    def test_deutz(self):
        daten = aggregator.aggregate_news("Köln-Deutz", demo=True)
        veedel = titel(daten, "veedel")
        self.assertTrue(any("Mensa" in t for t in veedel), veedel)
        self.assertEqual(daten["place"]["bezirk"], "Innenstadt")

    def test_karteileichen_werden_gefiltert(self):
        """Ein eingeschlafener Blog darf keine Jahre alten Artikel liefern."""
        from datetime import datetime, timedelta, timezone
        from news.aggregator import _zu_alt
        alt = Item(title="Post von 2019", link="https://example.invalid/a",
                         source="Blog",
                         published=datetime.now(timezone.utc) - timedelta(days=900))
        neu = Item(title="Post von heute", link="https://example.invalid/b",
                         source="Blog", published=datetime.now(timezone.utc))
        ohne = Item(title="Ohne Datum", link="https://example.invalid/c",
                          source="Blog")
        self.assertTrue(_zu_alt(alt))
        self.assertFalse(_zu_alt(neu))
        self.assertFalse(_zu_alt(ohne))   # kein Datum -> nicht verwerfen

    def test_umland_und_andere_staedte_fliegen_raus(self):
        """Polizei Köln berichtet auch aus Leverkusen, Reddit auch über Hamburg."""
        daten = aggregator.aggregate_news("Nippes", demo=True)
        alle = [i["title"] for s in daten["sections"] for i in s["artikel"]]
        self.assertFalse(any("Leverkusenerin" in x for x in alle), alle)
        self.assertFalse(any("Hamburg" in x for x in alle), alle)
        # … für die ganze Stadt genauso
        daten = aggregator.aggregate_news("Köln", demo=True)
        alle = [i["title"] for s in daten["sections"] for i in s["artikel"]]
        self.assertFalse(any("Leverkusenerin" in x for x in alle), alle)

    def test_stadtanfrage_ist_eine_liste(self):
        """Bei „Köln" gibt es kein Veedel – also genau eine Liste."""
        daten = aggregator.aggregate_news("Köln", demo=True)
        self.assertEqual(daten["place"]["kind"], "stadt")
        self.assertEqual(len(daten["sections"]), 1, daten["sections"])
        self.assertEqual(daten["stats"]["veedel_treffer"], 0)
        self.assertGreater(len(daten["sections"][0]["artikel"]), 5)

    def test_koeln_gesamt_hat_keine_veedel_filterung(self):
        daten = aggregator.aggregate_news("Köln", demo=True)
        self.assertTrue(daten["stats"]["artikel_behalten"] > 5)

    def test_warnung_bei_unbekanntem_ort(self):
        daten = aggregator.aggregate_news("Fantasiestadt", demo=True)
        self.assertTrue(any("erkannt" in w for w in daten["warnungen"]),
                        daten["warnungen"])

    def test_kompatibilitaets_shim(self):
        import crawler
        ergebnis = crawler.crawl_for_city("Köln-Nippes", max_items=10, demo=True)
        self.assertIn("stream", ergebnis)
        self.assertIn("summary", ergebnis)
        self.assertLessEqual(len(ergebnis["stream"]), 10)
        self.assertTrue(all(isinstance(i, dict) for i in ergebnis["stream"]))

    def test_diagnose_meldet_fehler(self):
        def kaputt(spec, force_refresh=False, demo=False):
            return SourceResult(name=spec.name, url=spec.url or spec.path, ok=False,
                                error="HTTP 403 (Reddit blockt diese IP)",
                                hint="Test-Hinweis", group=spec.group)

        orig = aggregator._hole_quelle
        aggregator._hole_quelle = staticmethod(kaputt)
        try:
            daten = aggregator.aggregate_news("Nippes")
        finally:
            aggregator._hole_quelle = orig

        self.assertEqual(daten["stats"]["artikel_behalten"], 0)
        fehler = [s for s in daten["sources"] if not s["ok"]]
        self.assertTrue(fehler)
        self.assertTrue(any("403" in f["error"] for f in fehler))
        self.assertTrue(any("Reddit" in w for w in daten["warnungen"]), daten["warnungen"])


class TestDemoModus(unittest.TestCase):
    """Der Demo-Modus ist Produktivcode (Vorschau/CI) – also auch getestet."""

    def test_demo_liefert_gespeicherte_feeds(self):
        daten = aggregator.aggregate_news("Nippes", demo=True)
        self.assertTrue(daten["demo"])
        self.assertTrue(any("Demo-Modus" in w for w in daten["warnungen"]))
        self.assertGreater(daten["stats"]["artikel_behalten"], 0)
        self.assertTrue(any("Demo-Daten" in s["used"] for s in daten["sources"]))

    def test_demo_ist_verfuegbar(self):
        from news import demo
        self.assertTrue(demo.verfuegbar())


# ==========================================================================
class TestWebApp(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        cls.client = flask_app.app.test_client()
        cls.flask_app = flask_app

    def test_startseite_rendert(self):
        r = self.client.get("/?ort=Nippes&demo=1")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("Lokal-Radar", html)
        self.assertIn("Etat-Kürzungen", html)
        self.assertIn("ansicht-themen", html)
        self.assertIn("Quellen-Protokoll", html)

    def test_api_json(self):
        r = self.client.get("/api/news?ort=Deutz&fmt=json&demo=1")
        self.assertEqual(r.status_code, 200)
        daten = r.get_json()
        self.assertEqual(daten["place"]["name"], "Deutz")
        self.assertTrue(daten["sections"])
        self.assertEqual(r.headers["Cache-Control"], "no-store, max-age=0")

    def test_api_html_fragment(self):
        r = self.client.get("/api/news?ort=Ehrenfeld&fmt=html&demo=1")
        daten = r.get_json()
        self.assertIn("html", daten)
        self.assertIn("class=\"karte", daten["html"])

    def test_orte_endpoint(self):
        r = self.client.get("/api/orte?q=s%C3%BCl")
        daten = r.get_json()
        self.assertTrue(any(o["name"] == "Sülz" for o in daten["orte"]), daten["orte"])

    def test_quellenplan_endpoint(self):
        r = self.client.get("/api/quellen?ort=S%C3%BCdstadt")
        daten = r.get_json()
        self.assertIn("neustadt-sued", " ".join(q["url"] for q in daten["quellen"]))

    def test_health(self):
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_themen_filter(self):
        r = self.client.get("/api/news?ort=Nippes&themen=medien&fmt=json&demo=1")
        daten = r.get_json()
        self.assertFalse(any(s["group"] == "foren" for s in daten["sources"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
