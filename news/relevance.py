# -*- coding: utf-8 -*-
"""Relevanz: Welcher Artikel gehört wirklich in welches Veedel?

Drei getrennte Probleme, die hier gelöst werden:

1. **Falscher Stadtteil.** Ein Treffer wird über den URL-Pfad (bei KSTA steht
   das Veedel direkt drin: ``/koeln/nippes/bilderstoeckchen/…``) und über den
   Text (Name, „Köln-<Veedel>", Sehenswürdigkeiten) bewertet. Artikel ohne
   jeden Ortsbezug fliegen raus – das ist der Grund, warum vorher Express-
   Shoppingmeldungen und r/worldnews im Stream landeten.

2. **Immer dieselben.** Dedup über Titel-Ähnlichkeit (KSTA, Rundschau und
   Express gehören zusammen und veröffentlichen dieselben Artikel) plus
   Round-Robin über die Quellen, damit nicht eine Quelle den Stream füllt.

3. **Besser aufteilen.** Kategorien statt „Gruppierung nach dem ersten Wort
   des Titels": Blaulicht, Verkehr, Politik, Kultur, Sport, Wirtschaft,
   Veedel, Community.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .fetch import Item
from .places import (BEZIRKE, LANDMARKS, NACHBARSTAEDTE, Place, norm,
                     slug)

# --------------------------------------------------------------------------
# Kategorien
# --------------------------------------------------------------------------
KATEGORIEN: dict[str, dict] = {
    "blaulicht": {"label": "Blaulicht", "icon": "🚨",
                  "info": "Polizei, Feuerwehr, Unfälle, Kriminalität"},
    "verkehr":   {"label": "Verkehr & Bau", "icon": "🚋",
                  "info": "KVB, Baustellen, Rad, Straße, Bahn"},
    "politik":   {"label": "Politik & Stadt", "icon": "🏛️",
                  "info": "Rat, Bezirksvertretung, Verwaltung, Beschlüsse"},
    "kultur":    {"label": "Kultur & Karneval", "icon": "🎭",
                  "info": "Konzerte, Bühnen, Museen, Jecken"},
    "sport":     {"label": "Sport", "icon": "⚽",
                  "info": "1. FC Köln, Haie, Viktoria, Breitensport"},
    "wirtschaft": {"label": "Wohnen & Wirtschaft", "icon": "🏗️",
                   "info": "Mieten, Neubau, Handel, Gastro, Jobs"},
    "community": {"label": "Foren & Community", "icon": "💬",
                  "info": "Reddit, Stadtportal, Veedel-Blogs"},
    "veedel":    {"label": "Veedel", "icon": "🏘️",
                  "info": "Alltag, Vereine, Feste, Schule, Nachbarschaft"},
}
KATEGORIE_REIHENFOLGE = ["blaulicht", "verkehr", "politik", "kultur",
                         "sport", "wirtschaft", "community", "veedel"]

_KAT_MUSTER: dict[str, list[str]] = {
    "blaulicht": [
        r"\bpolizei\b", r"\bpolizist", r"\bpressemitteilung\b", r"\bots\b", r"pol-k",
        r"\bfeuerwehr\b", r"\bbrand\b", r"\bfeuer\b", r"\bunfall\b", r"\bkollision\b",
        r"\bfahndung\b", r"\bzeugen\b", r"\bfestnahme\b", r"\bfestgenommen\b",
        r"\bdiebstahl\b", r"\bgestohlen\b", r"\beinbruch\b", r"\braub\b", r"\bueberfall\b",
        r"\bmesser\b", r"\bschuesse\b", r"\bgeschossen\b", r"\bwaffen?\b", r"\bdrogen\b",
        r"\b cannabis\b", r"\bbetrug\b", r"\bbetrueger\b", r"\bkriminal", r"\bverletzt",
        r"\blebensgefahr\b", r"\brettungswagen\b", r"\bgrosseinsatz\b", r"\beinsatzkraefte\b",
        r"\bexplosion\b", r"\bgefaehrlich\b", r"\bstichverletzung\b", r"\bvermisst\b",
        r"\bleiche\b", r"\btot\b", r"\bgetoetet\b", r"\bmord\b", r"\bkripo\b",
        r"\bstaatsanwaltschaft\b", r"\bgericht\b", r"\burteil\b", r"\bhaftbefehl\b",
        r"\bschockanruf\b", r"\btrickdieb", r"\bpyrotechnik\b", r"\bkampfmittel\b",
        r"\bbombe\b", r"\bentschaerfung\b", r"\bevakuier",
    ],
    "verkehr": [
        r"\bkvb\b", r"\bstadtbahn\b", r"\bstrassenbahn\b", r"\bhaltestelle\b",
        r"\bbus\b", r"\bbusse\b", r"\bs-bahn\b", r"\bregionalbahn\b", r"\bbahn\b",
        r"\bstau\b", r"\bsperrung\b", r"\bgesperrt\b", r"\bbaustelle\b", r"\bbauarbeiten\b",
        r"\bradweg\b", r"\bfahrrad\b", r"\bradfahr", r"\bradverkehr\b", r"\bprotected bike\b",
        r"\bautobahn\b", r"\b[aA]\s?\d{1,2}\b", r"\bparken\b", r"\bparkplatz\b",
        r"\btempo\s?30\b", r"\bblitzer\b", r"\bgeschwindigkeitsmess", r"\bverkehr\b",
        r"\bumleitung\b", r"\bbruecke\b", r"\bbruecken\b", r"\bzoobruecke\b",
        r"\bmilitarring\b", r"\bguertel\b", r"\bgleise?\b", r"\bdeutsche bahn\b",
        r"\bflughafe[n]?\b", r"\bbetriebslage\b", r"\bfussgaenger\b", r"\bverkehrsunfall\b",
    ],
    "politik": [
        r"\brat\b", r"\bstadtrat\b", r"\bbezirksvertretung\b", r"\bbv\b",
        r"\bverwaltung\b", r"\bstadt koeln\b", r"\bhaushalt\b", r"\betat\b",
        r"\bbeschluss\b", r"\bbeschliesst\b", r"\bwahl\b", r"\bwaehler\b",
        r"\bbuergermeister\b", r"\boberbuergermeister\b", r"\bdezernent\b",
        r"\bbeigeordnete\b", r"\bsatzung\b", r"\bbebauungsplan\b", r"\bstadtplanung\b",
        r"\bdemo\b", r"\bdemonstration\b", r"\bprotest\b", r"\bpetition\b",
        r"\bcdu\b", r"\bspd\b", r"\bgruene?\b", r"\bafd\b", r"\bfpd\b", r"\blinke\b",
        r"\bvolt\b", r"\bklima\b", r"\bfoerder", r"\bzuschuss\b", r"\bkuerzung",
        r"\bbeteiligung\b", r"\bbuergerbeteiligung\b", r"\brathaus\b",
    ],
    "kultur": [
        r"\bkonzert\b", r"\bmuseum\b", r"\btheater\b", r"\boper\b", r"\bbuehne\b",
        r"\bausstellung\b", r"\bkino\b", r"\bmusik\b", r"\bfestival\b", r"\bkultur\b",
        r"\bkarneval\b", r"\bjeck", r"\bkoelsch\b", r"\bprinz\b", r"\bdreigestirn\b",
        r"\brosenmontag\b", r"\bsitzung\b", r"\blit\.?\s?cologne\b", r"\bbuch\b",
        r"\bautor\b", r"\bkuenstler\b", r"\bgalerie\b", r"\bphilharmonie\b",
        r"\blanxess\b", r"\bpalladium\b", r"\bclub\b", r"\bkneipe\b", r"\bgastro\b",
        r"\brestaurant\b", r"\bweihnachtsmarkt\b", r"\bkirmes\b", r"\bvolksfest\b",
        r"\bjubilaeum\b", r"\bkoelner haie\b",
    ],
    "sport": [
        r"\b1\.?\s?fc\b", r"\bfc koeln\b", r"\bgeissboeck", r"\brheinenergie",
        r"\bstadion\b", r"\bfussball\b", r"\bbundesliga\b", r"\btrainer\b",
        r"\btransfer\b", r"\bspiel\b", r"\bsieg\b", r"\bniederlage\b", r"\btor\b",
        r"\bhaie\b", r"\bviktoria\b", r"\bhandball\b", r"\bbasketball\b",
        r"\bhockey\b", r"\bschwimm", r"\bmarathon\b", r"\bfussballspiel\b",
        r"\bderby\b", r"\bfans?\b", r"\bultras?\b", r"\bsport\b", r"\bolympia\b",
        r"\brennbahn\b", r"\bfc-prof", r"\bspieltag\b",
    ],
    "wirtschaft": [
        r"\bmiete\b", r"\bmieten\b", r"\bwohnung\b", r"\bwohnungen\b", r"\bwohnen\b",
        r"\bneubau\b", r"\bbauprojekt\b", r"\bimmobilie", r"\bquartier\b",
        r"\bwohnungs", r"\bmieter\b", r"\bvermieter\b", r"\bhandel\b", r"\bgeschaeft\b",
        r"\blaeden\b", r"\beroeffn", r"\bschliess", r"\binsolvenz\b", r"\bunternehmen\b",
        r"\barbeitsplaetze\b", r"\bjobs?\b", r"\bwirtschaft\b", r"\binvestor\b",
        r"\bmillionen\b", r"\bfoerderung\b", r"\bkiosk\b", r"\bsupermarkt\b",
        r"\beinkauf\b", r"\bpreise?\b", r"\binflation\b", r"\bgewerbe\b",
        r"\bumbau\b", r"\bsanier", r"\bbaustart\b", r"\bwohnungsnot\b",
    ],
    "veedel": [
        r"\bveedel\b", r"\bstraßenfest\b", r"\bstrassenfest\b", r"\bverein\b",
        r"\bnachbarschaft\b", r"\bschule\b", r"\bkita\b", r"\bkindergarten\b",
        r"\bbuergerzentrum\b", r"\bbueze\b", r"\bwochenmarkt\b", r"\bfest\b",
        r"\bfreizeit\b", r"\bspielplatz\b", r"\bpark\b", r"\bgruen\b", r"\bbaeume?\b",
        r"\bkirche\b", r"\bfriedhof\b", r"\bsenioren\b", r"\bjugend\b",
        r"\behrenamt\b", r"\binitiative\b", r"\banwohner\b", r"\bnachbarn\b",
    ],
}
_KAT_REGEX = {k: [re.compile(p, re.I) for p in v] for k, v in _KAT_MUSTER.items()}

# --------------------------------------------------------------------------
# Müll-Filter: Shopping/Affiliate/Werbung hat in einem Lokal-Stream nichts zu suchen
# --------------------------------------------------------------------------
_JUNK_PATH = re.compile(
    r"(shoppingwelt|shopping-tipps|deal|angebot|gutschein|anzeig|sponsored|"
    r"werbelink|affiliate|witz-des-tages|horoskop|lottozahlen|gewinnspiel|"
    r"produktempfehlung|vergleich|testberichte)", re.I)
_JUNK_TITLE = re.compile(
    r"(\b\d{1,3}\s?%\s?(rabatt|sparen|reduziert|günstiger)|\bim angebot\b|"
    r"\bjetzt (kaufen|sichern|bestellen|sparen)\b|\bsale\b|\bdeal(s)?\b|"
    r"\bamazon\b|\blidl\b|\baldi\b.*\breduziert\b)", re.I)


def is_junk(item: Item) -> bool:
    if _JUNK_PATH.search(item.url_slug or "") or _JUNK_PATH.search(item.link or ""):
        return True
    return bool(_JUNK_TITLE.search(item.title or ""))


# --------------------------------------------------------------------------
# Orts-Matching
# --------------------------------------------------------------------------

# „Polizei Köln" oder „Stadt Köln" sind Behördennamen, keine Ortsangaben.
# Ohne diese Bereinigung gälte jede Meldung der Kölner Polizei (die auch für
# Leverkusen zuständig ist) als Köln-Treffer. Muster laufen auf normiertem Text.
INSTITUTIONEN = re.compile(
    r"(?<![a-z0-9])(?:"
    r"polizei(?:praesidium|inspektion)?\s+koeln|"
    r"koeln\s*\(ots\)|"
    r"stadt\s+koeln|"
    r"1\.?\s?fc\s+koeln|"
    r"koelner\s+stadt\s+anzeiger|koelner\s+express|koelner\s+rundschau|"
    r"koelner\s+haie|koelner\s+verkehrsbetriebe|koelner\s+dom|"
    r"radio\s+koeln|th\s+koeln|universitaet\s+koeln|"
    r"polizei\s+nrw|pressestelle\s+koeln"
    r")(?![a-z0-9])")

# „Bezirk Nippes" meint den Bezirk, nicht das Veedel Nippes. Für die
# Veedel-Suche wird diese Phrase vorher entfernt.
BEZIRK_PHRASE = re.compile(
    r"(?<![a-z0-9])(?:(?:stadt)?bezirk(?:svertretung|s)?|bv)[\s\-]+[a-z]+(?![a-z0-9])")

# Namen, zu denen keine Adjektivform gebildet werden darf
# („Weißer Wagen" ist kein Artikel über Weiß).
KEIN_ADJEKTIV = {"weiss", "lind", "eil", "wahn", "poll", "esch", "seeberg"}

# URL-Segmente, die einen Kölner Stadtbezirk kennzeichnen
BEZIRK_SLUGS = set(BEZIRKE.values())

# Meldungen aus dem Umland/anderen Städten – mit Adjektivformen
# („Leverkusenerin"), aber nur wenn im Text kein Köln vorkommt.
NACHBAR_REGEX = re.compile(
    r"(?<![a-z0-9])(?:" + "|".join(
        re.escape(norm(s)).replace(r"\ ", r"[\s\-]+") for s in NACHBARSTAEDTE)
    + r")(?:er|erin|ern|ers)?(?![a-z0-9])")


def _wort_regex(keyword: str, prefix_optional: bool = True,
                ende_offen: bool = False) -> re.Pattern:
    """Muster mit deutschen Wortgrenzen und optionalem „Köln-"-Präfix.

    Der durchsuchte Text liegt **normiert** vor (klein, ä→ae, Bindestriche ->
    Leerzeichen, „Strasse" -> „str"), deshalb genügt ``[a-z0-9]`` als Grenze.

    ``ende_offen`` erlaubt Treffer wie „Neusser Strasse" für das Kürzel
    „neusser str" – bei Sehenswürdigkeiten üblich, bei Ortsnamen gefährlich.
    """
    parts = [p for p in keyword.split() if p]
    body = r"[\s\-]+".join(re.escape(p) for p in parts)
    if prefix_optional:
        prefix = r"(?:(?:koeln|cologne|stadtteil|veedel|bezirk)[\s\-]+)?"
    else:
        prefix = r"(?:koeln|cologne)[\s\-]+"
    ende = r"(?![0-9])" if ende_offen else r"(?![a-z0-9])"
    return re.compile(r"(?<![a-z0-9])" + prefix + body + ende)


def _offen(keyword: str) -> bool:
    """Letztes Wort ist ein Kürzel wie „str"/„pl" -> offenes Wortende erlauben."""
    letztes = keyword.split()[-1] if keyword.split() else ""
    return letztes in ("str", "pl") or letztes.endswith("str") or letztes.endswith("pl")


@dataclass
class Matcher:
    """Alles, was zum Bewerten eines Artikels für einen Ort nötig ist."""

    place: Place
    stadtteil_slugs: list[str] = field(default_factory=list)
    bezirk_slug: str = ""
    eigene_orte: set[str] = field(default_factory=set)
    name_regex: list[tuple[re.Pattern, str]] = field(default_factory=list)
    strict_name_regex: list[tuple[re.Pattern, str]] = field(default_factory=list)
    adjektiv_regex: list[tuple[re.Pattern, str]] = field(default_factory=list)
    landmark_regex: list[tuple[re.Pattern, str]] = field(default_factory=list)
    bezirk_regex: list[tuple[re.Pattern, str]] = field(default_factory=list)
    city_regex: re.Pattern | None = None
    mehrdeutig: bool = False

    @classmethod
    def build(cls, place: Place) -> "Matcher":
        m = cls(place=place)
        m.mehrdeutig = place.mehrdeutig
        m.stadtteil_slugs = [slug(s) for s in place.stadtteile] + list(place.slugs)
        m.stadtteil_slugs = [s for s in dict.fromkeys(m.stadtteil_slugs) if s]
        m.bezirk_slug = place.bezirk_slug or ""
        m.eigene_orte = set(place.stadtteile) | {place.name}

        # Bei einer Stadt-Anfrage („Köln") ist der Stadtname kein Veedel:
        # sonst wäre jede Meldung, die „Köln" enthält, ein Veedel-Treffer.
        if place.kind in ("stadt", "unbekannt"):
            namen = []
        else:
            namen = place.stadtteile or [place.name]
            if place.kind == "veedel":
                namen = [place.name] + namen

        for name in namen:
            kw = norm(name)
            m.name_regex.append((_wort_regex(kw), name))
            m.strict_name_regex.append((_wort_regex(kw, prefix_optional=False), name))
            for teil in re.split(r"[/\-]", name):
                if len(teil) > 3 and norm(teil) != kw:
                    m.name_regex.append((_wort_regex(norm(teil)), teil))
                    m.strict_name_regex.append(
                        (_wort_regex(norm(teil), prefix_optional=False), teil))
            # Adjektivform: „Deutzer Freiheit", „Kalker Hauptstraße", „Niehler Hafen"
            teile = [x for x in kw.split() if x]
            letztes = teile[-1] if teile else ""
            if letztes and letztes not in KEIN_ADJEKTIV and len(letztes) >= 4:
                stamm = r"[\s\-]+".join(re.escape(x) for x in teile)
                m.adjektiv_regex.append(
                    (re.compile(rf"(?<![a-z0-9]){stamm}(?:er|ern|ers)(?![a-z0-9])"),
                     name))

        seen = set()
        for st in place.stadtteile or [place.name]:
            for lm in LANDMARKS.get(st, []):
                if lm in seen:
                    continue
                seen.add(lm)
                kw = norm(lm)
                m.landmark_regex.append((_wort_regex(kw, ende_offen=_offen(kw)), lm))

        if place.bezirk:
            m.bezirk_regex.append((_wort_regex(norm(place.bezirk)), place.bezirk))

        m.city_regex = re.compile(r"(?<![a-z0-9])(?:koeln|cologne)(?![a-z0-9])")
        return m


# --------------------------------------------------------------------------
# Register aller Kölner Ortsnamen – erkennt, ob eine Meldung über ein
# *anderes* Veedel spricht (dann gehört sie nicht in diese Ansicht).
# --------------------------------------------------------------------------
_ORTS_REGISTER: list[tuple[re.Pattern, str, str]] | None = None


def orts_register() -> list[tuple[re.Pattern, str, str]]:
    global _ORTS_REGISTER
    if _ORTS_REGISTER is None:
        from .places import STADTTEIL_BEZIRK, VEEDEL
        reg: list[tuple[re.Pattern, str, str]] = []
        for st, bez in STADTTEIL_BEZIRK.items():
            reg.append((_wort_regex(norm(st)), st, bez))
            for teil in st.split("/"):
                if len(teil) > 3:
                    reg.append((_wort_regex(norm(teil)), st, bez))
        for ved, (st, _) in VEEDEL.items():
            reg.append((_wort_regex(norm(ved)), st,
                        STADTTEIL_BEZIRK.get(st, "Innenstadt")))
        # lange Namen zuerst: „Neuehrenfeld" vor „Ehrenfeld"
        reg.sort(key=lambda eintrag: -len(eintrag[1]))
        _ORTS_REGISTER = reg
    return _ORTS_REGISTER


_SLUG_REGISTER: dict[str, tuple[str, str]] | None = None


def slug_register() -> dict[str, tuple[str, str]]:
    global _SLUG_REGISTER
    if _SLUG_REGISTER is None:
        from .places import slug_zu_ort
        _SLUG_REGISTER = slug_zu_ort()
    return _SLUG_REGISTER


def fremder_ort(text: str, segments: list[str], m: Matcher,
                ksta_form: bool) -> tuple[str, str] | None:
    """Liefert ``(Stadtteil, Bezirk)``, wenn die Meldung woanders spielt."""
    # 1) URL-Pfad ist bei KSTA eindeutig
    if ksta_form and len(segments) >= 3:
        seg = re.sub(r"-\d+$", "", segments[2])
        treffer = slug_register().get(seg)
        if treffer and treffer[0] not in m.eigene_orte:
            return treffer
    # 2) Text
    for rx, name, bezirk in orts_register():
        if name in m.eigene_orte:
            continue
        if rx.search(text):
            return name, bezirk
    return None


def match_place(item: Item, m: Matcher, source_scope: str = "",
                item_kind: str = "") -> tuple[float, str, list[str]]:
    """Bewertet einen Artikel: ``(score, scope, evidence)``.

    scope: ``veedel`` > ``bezirk`` > ``koeln``. Score 0 = kein Ortsbezug
    (oder die Meldung spielt nachweislich in einem anderen Stadtbezirk).

    Reihenfolge ist Absicht:

    1. URL-Pfad – bei KSTA steht das Veedel als eigenes Segment drin.
       Wichtig: ``/koeln/{bezirk}/{stadtteil}/…``. Würde man alle Segmente
       durchsuchen, fände man bei „Nippes" den Bezirks-Slug auch im
       Weidenpesch-Artikel – genau der alte Fehler.
    2. Ortsname / Adjektivform im Text („Kölner Stadt-Anzeiger" & Co. zählen
       dabei *nicht* als Ortsbeleg, „Bezirk Nippes" auch nicht).
    3. Sehenswürdigkeit oder Straße.
    4. Erst dann: spielt die Meldung in einem *anderen* Veedel?
    5. Bezirk, 6. Stadt.
    """
    text = norm(f"{item.title} {item.teaser}")
    text_veedel = BEZIRK_PHRASE.sub(" ", text)
    text_ort = INSTITUTIONEN.sub(" ", text)
    hat_koeln = bool(m.city_regex and m.city_regex.search(text_ort))

    segments = [s for s in (item.url_slug or "").split("/") if s]
    ev: list[str] = []

    ksta_form = (segments[:1] == ["koeln"] and len(segments) >= 3
                 and segments[1] in BEZIRK_SLUGS)
    scan = segments[2:] if ksta_form else segments
    bezirk_segment = segments[1] if ksta_form else ""
    stadtteil_slugs = set(m.stadtteil_slugs)

    # 1) Veedel als eigenes Pfadsegment
    for seg in scan:
        if re.sub(r"-\d+$", "", seg) in stadtteil_slugs:
            return 100.0, "veedel", [f"URL-Pfad „{seg}“"]

    # 2) Veedel steckt im Artikel-Slug (z. B. „…-in-koeln-zollstock-…").
    #    Bei KSTA-Pfaden überspringen: Dort ist Segment 3 maßgeblich, und der
    #    Überschriften-Slug beginnt oft nur mit dem Bezirksnamen.
    if not ksta_form:
        for seg in scan:
            for st_slug in m.stadtteil_slugs:
                if len(st_slug) > 3 and re.search(
                        rf"(?<![a-z0-9]){re.escape(st_slug)}(?![a-z0-9])", seg):
                    return 90.0, "veedel", [f"URL-Slug „{st_slug}“"]

    # 2b) KSTA hat den Artikel eindeutig einem anderen Veedel zugeordnet.
    #     Die redaktionelle Ablage ist stärker als ein Textfund („BV Nippes"),
    #     aber schwächer als der eigene Name im Titel („Kampagne in Riehl").
    if ksta_form and len(segments) >= 3 and m.eigene_orte:
        fremd_url = slug_register().get(re.sub(r"-\d+$", "", segments[2]))
        if fremd_url and fremd_url[0] not in m.eigene_orte:
            name, bezirk = fremd_url
            if bezirk != m.place.bezirk:
                return 0.0, "", [f"handelt von {name} (Bezirk {bezirk})"]
            titel = BEZIRK_PHRASE.sub(" ", norm(item.title))
            if any(rx.search(titel) for rx, _ in m.strict_name_regex + m.name_regex):
                return 85.0, "veedel", [f"„{m.place.name}“ im Titel (URL: {name})"]
            return 50.0, "bezirk", [f"Nachbarveedel {name} (URL)"]

    # 3) Ortsname im Text (mit Adjektivform)
    if not m.mehrdeutig:
        for rx, label in m.name_regex + m.adjektiv_regex:
            if rx.search(text_veedel):
                return 85.0, "veedel", [f"„{label}“ im Text"]
    else:
        # mehrdeutige Namen („Poll", „Kalk", „Deutz") brauchen einen Köln-Beleg,
        # der nicht nur aus dem Namen der Behörde besteht
        for rx, label in m.strict_name_regex:
            if rx.search(text_veedel):
                return 85.0, "veedel", [f"„{label}“ im Text"]
        if hat_koeln:
            for rx, label in m.name_regex + m.adjektiv_regex:
                if rx.search(text_veedel):
                    return 78.0, "veedel", [f"„{label}“ mit Köln-Bezug"]

    # 4) Sehenswürdigkeit / Straße
    for rx, label in m.landmark_regex:
        if rx.search(text):
            return 62.0, "veedel", [f"Ort „{label}“"]

    # 5) spielt die Meldung in einem anderen Veedel?
    #    (Bei einer Stadt-Anfrage gibt es kein „fremd": ganz Köln ist gesucht.)
    fremd = fremder_ort(text_veedel, segments, m, ksta_form) if m.eigene_orte else None
    if fremd:
        name, bezirk = fremd
        if bezirk == m.place.bezirk:
            return 50.0, "bezirk", [f"Nachbarveedel {name}"]
        return 0.0, "", [f"handelt von {name} (Bezirk {bezirk})"]

    # 6) Bezirk
    if bezirk_segment and m.bezirk_slug and bezirk_segment == m.bezirk_slug:
        return _bonus(50.0, "bezirk", [f"Bezirk {m.place.bezirk} (URL)"], source_scope)
    if m.bezirk_slug:
        for seg in segments[1:]:
            if re.search(rf"(?<![a-z0-9]){re.escape(m.bezirk_slug)}(?![a-z0-9])", seg):
                return _bonus(48.0, "bezirk",
                              [f"Bezirk {m.place.bezirk} (URL-Slug)"], source_scope)
    # Bei mehrdeutigen Bezirken („Kalk") gilt dasselbe wie beim Stadtteil:
    # ohne Köln-Beleg kein Treffer, sonst landet Chemie-Kalk im Veedel-Stream.
    if not (m.mehrdeutig and not hat_koeln):
        for rx, label in m.bezirk_regex:
            if rx.search(text):
                return _bonus(48.0, "bezirk", [f"Bezirk „{label}“"], source_scope)

    # 7) spielt die Meldung ganz woanders? (Polizei Köln berichtet auch aus
    #    Leverkusen; auf r/Koeln landet gelegentlich ein Post über Hamburg)
    if not hat_koeln and NACHBAR_REGEX.search(text_ort):
        return 0.0, "", ["spielt außerhalb Kölns"]

    # 8) immerhin Köln (ohne Behörden-Phrase)
    if hat_koeln:
        return _bonus(12.0, "koeln", ["Köln-Bezug"], source_scope)

    # 9) Die Quelle selbst ist der Ortsbeleg: Pressemeldungen von Stadt und
    #    Polizei erscheinen nur für Köln (Leverkusen wurde oben aussortiert),
    #    und die Köln-Kanäle von EXPRESS/koeln.de/Rundschau werden redaktionell
    #    auf die Stadt kuratiert.
    if item_kind in ("presse", "polizei"):
        return _bonus(12.0, "koeln", ["offizielle Meldung der Stadt"], source_scope)
    if source_scope == "koeln" and _ist_koeln_kanal(item_kind):
        return _bonus(12.0, "koeln", ["Köln-Kanal der Redaktion"], source_scope)

    return 0.0, "", ev


def _ist_koeln_kanal(item_kind: str) -> bool:
    """True für redaktionelle Meldungen aus einem stadtweit kuratierten Kanal."""
    return item_kind in ("news", "sport", "")


def _bonus(score: float, scope: str, ev: list[str],
           source_scope: str) -> tuple[float, str, list[str]]:
    """Vertrauensbonus der Quelle.

    Ein Stadtteil-Feed ist eine redaktionelle Zuordnung und zählt deshalb mehr
    als ein fehlender Ortsname im Text. *Nicht* angewendet wird der Bonus, wenn
    die Meldung nachweislich in einem anderen Veedel spielt (Schritt 5) – das
    war der Kern des alten Fehlers.
    """
    if source_scope == "veedel":
        return max(score, 92.0), "veedel", ev or ["aus dem Veedel-Feed"]
    if source_scope == "bezirk":
        if score <= 0:
            return 46.0, "bezirk", ev or ["aus dem Bezirks-Feed"]
        return max(score, 46.0), scope or "bezirk", ev
    if source_scope == "region":
        return max(score, 40.0), scope or "region", ev
    return score, scope, ev


# --------------------------------------------------------------------------
# Kategorien
# --------------------------------------------------------------------------
def categorize(item: Item, forced: str = "") -> str:
    """Ordnet einen Artikel einer Kategorie zu."""
    if forced and forced in KATEGORIEN:
        return forced
    if item.kind == "forum":
        return "community"
    if item.kind == "polizei":
        return "blaulicht"

    text = f"{item.title} {item.teaser}"
    best, best_hits = "veedel", 0
    for kat in KATEGORIE_REIHENFOLGE:
        if kat == "community":
            continue
        hits = sum(1 for rx in _KAT_REGEX[kat] if rx.search(text))
        if hits > best_hits:
            best, best_hits = kat, hits
    if best_hits == 0 and item.kind == "presse":
        return "politik"
    return best


# --------------------------------------------------------------------------
# Dedup + Vielfalt
# --------------------------------------------------------------------------
_STOP = set("der die das und oder im in von zu fuer mit auf dem den des ein eine "
            "einer eines einem einen ist sind war wird werden nach als an aus bei "
            "nicht nur noch auch wie um ueber vor zwischen koeln köln".split())


def _titel_schluessel(title: str) -> str:
    t = norm(title)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _titel_kern(title: str) -> str:
    """Titel ohne Dachzeile.

    Die DuMont-Portale (KSTA, Rundschau, EXPRESS) veröffentlichen dieselbe
    Meldung gerne mit anderer Dachzeile:
    „Neueröffnung: Einrichtungshaus Butlers kommt nach Nippes" (KSTA) und
    „Einrichtungshaus Butlers kommt nach Nippes" (EXPRESS) sind *ein* Artikel.
    """
    if ":" in title:
        kern = _titel_schluessel(title.rsplit(":", 1)[-1])
        if len(kern) > 15:
            return kern
    return _titel_schluessel(title)


def _signifikant(title: str, n: int = 6) -> list[str]:
    words = [w for w in _titel_schluessel(title).split() if w not in _STOP and len(w) > 2]
    return words[:n]


def _aehnlich(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def dedupe(items: list[Item]) -> list[Item]:
    """Entfernt Dubletten (auch quelleübergreifend) und führt Quellen zusammen."""
    kept: list[Item] = []
    meta: list[tuple[str, str, list[str]]] = []       # (schlüssel, kern, signifikant)
    by_exact: dict[str, Item] = {}
    by_kern: dict[str, Item] = {}

    for item in items:
        key = _titel_schluessel(item.title)
        if not key:
            continue
        kern = _titel_kern(item.title)
        sig = _signifikant(item.title)

        hit = by_exact.get(key)
        if hit is None and len(kern) > 15:
            kandidat = by_kern.get(kern)
            if kandidat is not None and _aehnlich(key, _titel_schluessel(kandidat.title)) >= 0.7:
                hit = kandidat

        if hit is None:
            for idx in range(max(0, len(kept) - 120), len(kept)):
                other = kept[idx]
                o_key, o_kern, o_sig = meta[idx]
                if (len(sig) >= 4 and len(o_sig) >= 4 and sig[:4] == o_sig[:4]
                        and _aehnlich(key, o_key) >= 0.8):
                    hit = other
                    break
                if kern and o_kern and kern == o_kern and len(kern) > 15 \
                        and _aehnlich(key, o_key) >= 0.7:
                    hit = other
                    break
                if _aehnlich(key, o_key) > 0.90:
                    hit = other
                    break

        if hit is not None:
            if item.source not in hit.also_from and item.source != hit.source:
                hit.also_from.append(item.source)
            # bessere Daten übernehmen
            if item.score > hit.score:
                hit.score, hit.scope, hit.evidence = item.score, item.scope, item.evidence
            if not hit.teaser and item.teaser:
                hit.teaser = item.teaser
            if not hit.image and item.image:
                hit.image = item.image
            if not hit.published and item.published:
                hit.published = item.published
            continue

        by_exact[key] = item
        by_kern[kern] = item
        kept.append(item)
        meta.append((key, kern, sig))
    return kept


def vielfalt(items: list[Item], max_pro_quelle: int = 8) -> list[Item]:
    """Round-Robin über die Quellen, damit keine Quelle den Stream dominiert.

    Das ist der eigentliche Fix für „immer die gleichen Einträge": vorher
    wurde stur nach Datum sortiert und ein einziger Feed konnte die ersten
    30 Plätze komplett belegen.
    """
    items = sorted(items, key=lambda i: (-i.score, i.published is None,
                                         -(i.published.timestamp() if i.published else 0)))
    buckets: dict[str, list[Item]] = {}
    for it in items:
        buckets.setdefault(it.source, []).append(it)

    out: list[Item] = []
    round_no = 0
    while True:
        added = False
        for quelle in sorted(buckets, key=lambda q: -max(
                (i.score for i in buckets[q]), default=0)):
            liste = buckets[quelle]
            if round_no < len(liste) and round_no < max_pro_quelle:
                out.append(liste[round_no])
                added = True
        if not added:
            break
        round_no += 1
    return out


def sortieren(items: list[Item]) -> list[Item]:
    """Scope zuerst, dann Relevanz, dann Alter."""
    scope_rank = {"veedel": 0, "bezirk": 1, "region": 1, "koeln": 2}
    return sorted(items, key=lambda i: (
        scope_rank.get(i.scope, 3),
        -i.score,
        i.published is None,
        -(i.published.timestamp() if i.published else 0),
    ))
