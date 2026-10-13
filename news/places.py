# -*- coding: utf-8 -*-
"""Ortsauflösung für Köln.

Das ist die Grundlage für die wichtigste Korrektur an der App:
Früher war die Quellenliste *hart auf Köln-Deutz verdrahtet* – egal was man
eingegeben hat. Dadurch kamen bei „Ehrenfeld" oder „Nippes" einfach die
Deutz-Artikel (und immer dieselben).

Hier wird eine Eingabe jetzt sauber aufgelöst in:

* einen der 9 Kölner Stadtbezirke,
* einen der 86 offiziellen Stadtteile,
* ein „kölsches Veedel" (Südstadt, Belgisches Viertel, Kwartier Latäng …),
* eine KSTA-Region (Bonn, Leverkusen, Rhein-Erft …) oder
* eine fremde Stadt (dann greift das generische Fallback-Profil).

Zu jedem Ort gehören die URL-Slugs der Stadtteil-Feeds, die Suchbegriffe
(inkl. Sehenswürdigkeiten/Straßen) und die Information, ob der Name mehrdeutig
ist („Poll", „Kalk", „Brück" … matchen sonst in fremden Texten).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

CITY = "Köln"

# --------------------------------------------------------------------------
# Normalisierung (ä -> ae, ß -> ss, Leerzeichen -> Bindestrich …)
# KSTA/koeln.de verwenden genau diese Schreibweise in ihren URLs.
# --------------------------------------------------------------------------
_TRANSLIT = {
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "é": "e", "è": "e", "ê": "e", "à": "a", "á": "a", "â": "a",
    "ó": "o", "ò": "o", "ô": "o", "ú": "u", "ù": "u", "û": "u",
    "í": "i", "ì": "i", "î": "i", "ç": "c", "ñ": "n",
}


def translit(text: str) -> str:
    """Deutsch-taugliche Transliteration (ä→ae) statt Unicode-Zerlegung (ä→a)."""
    out = []
    for ch in text.lower():
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        else:
            out.append(unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode())
    return "".join(out)


def slug(text: str) -> str:
    """URL-Slug: klein, transliteriert, Nicht-Buchstaben werden zu '-'.

    >>> slug("Bocklemünd/Mengenich")
    'bocklemuend-mengenich'
    >>> slug("Köln-Südstadt")
    'koeln-suedstadt'
    """
    s = translit(text)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return re.sub(r"-{2,}", "-", s)


def norm(text: str) -> str:
    """Normierter Fließtext für das Keyword-Matching.

    Bindestriche werden zu Leerzeichen (damit „Köln-Kalk" als „koeln kalk"
    matcht) und „Strasse" wird zu „str" gekürzt – in den Feeds steht mal
    „Neusser Straße", mal „Neusser Str.", die Landmark-Liste nutzt „str".
    """
    s = translit(text)
    s = s.replace("-", " ")
    s = re.sub(r"\bstrasse\b", "str", s)
    return re.sub(r"\s+", " ", s).strip()


def slug_zu_ort() -> dict[str, tuple[str, str]]:
    """URL-Slug -> (Stadtteil, Bezirk) für alle 86 Stadtteile.

    Enthält auch die ``-veedel``-Variante, mit der KSTA Stadtteile benennt,
    die wie ihr Bezirk heißen (``nippes/nippes-veedel``).
    """
    out: dict[str, tuple[str, str]] = {}
    for bezirk, stadtteile in STADTTEILE.items():
        for st in stadtteile:
            s = slug(st)
            out[s] = (st, bezirk)
            out[f"{s}-veedel"] = (st, bezirk)
            for teil in re.split(r"[/]", st):
                if len(slug(teil)) > 3:
                    out.setdefault(slug(teil), (st, bezirk))
    return out


# --------------------------------------------------------------------------
# Stadtbezirke und die 86 Stadtteile (Quelle: koeln.de/leben/stadtteile)
# Wert = der KSTA-Slug des Bezirksfeeds.
# --------------------------------------------------------------------------
BEZIRKE: dict[str, str] = {
    "Innenstadt": "koelner-innenstadt",
    "Rodenkirchen": "rodenkirchen",
    "Lindenthal": "lindenthal",
    "Ehrenfeld": "ehrenfeld",
    "Nippes": "nippes",
    "Chorweiler": "chorweiler",
    "Porz": "porz",
    "Kalk": "kalk",
    "Mülheim": "muelheim",
}

STADTTEILE: dict[str, list[str]] = {
    "Innenstadt": [
        "Altstadt-Nord", "Neustadt-Nord", "Altstadt-Süd", "Neustadt-Süd", "Deutz",
    ],
    "Rodenkirchen": [
        "Bayenthal", "Godorf", "Hahnwald", "Immendorf", "Marienburg", "Meschenich",
        "Raderberg", "Raderthal", "Rodenkirchen", "Rondorf", "Sürth", "Weiß", "Zollstock",
    ],
    "Lindenthal": [
        "Braunsfeld", "Junkersdorf", "Klettenberg", "Lindenthal", "Lövenich",
        "Müngersdorf", "Sülz", "Weiden", "Widdersdorf",
    ],
    "Ehrenfeld": [
        "Bickendorf", "Bocklemünd/Mengenich", "Ehrenfeld", "Neuehrenfeld",
        "Ossendorf", "Vogelsang",
    ],
    "Nippes": [
        "Bilderstöckchen", "Longerich", "Mauenheim", "Niehl", "Nippes", "Riehl",
        "Weidenpesch",
    ],
    "Chorweiler": [
        "Blumenberg", "Chorweiler", "Esch/Auweiler", "Fühlingen", "Heimersdorf",
        "Lindweiler", "Merkenich", "Pesch", "Roggendorf/Thenhoven", "Seeberg",
        "Volkhoven/Weiler", "Worringen",
    ],
    "Porz": [
        "Eil", "Elsdorf", "Ensen", "Finkenberg", "Gremberghoven", "Grengel", "Langel",
        "Libur", "Lind", "Poll", "Porz", "Urbach", "Wahn", "Wahnheide", "Westhoven",
        "Zündorf",
    ],
    "Kalk": [
        "Brück", "Höhenberg", "Humboldt/Gremberg", "Kalk", "Merheim", "Neubrück",
        "Ostheim", "Rath/Heumar", "Vingst",
    ],
    "Mülheim": [
        "Buchforst", "Buchheim", "Dellbrück", "Dünnwald", "Flittard", "Höhenhaus",
        "Holweide", "Mülheim", "Stammheim",
    ],
}

# Stadtteil -> Bezirk (umgekehrte Blickrichtung)
STADTTEIL_BEZIRK: dict[str, str] = {
    st: bez for bez, sts in STADTTEILE.items() for st in sts
}

# Namen, die als normales Wort in fremden Texten vorkommen können.
# Bei diesen verlangt der Relevanz-Check zusätzlich einen Köln-Beleg.
MEHRDEUTIG = {
    "poll", "lind", "eil", "wahn", "pesch", "kalk", "weiden", "brueck", "niehl",
    "ostheim", "merheim", "urbach", "elsdorf", "langel", "libur", "seeberg",
    "weiss", "suerth", "deutz", "holweide", "flittard", "godorf",
}

# --------------------------------------------------------------------------
# Kölsche Veedel (inoffiziell) -> offizieller Stadtteil + eigene Suchbegriffe
# --------------------------------------------------------------------------
VEEDEL: dict[str, tuple[str, list[str]]] = {
    "Südstadt": ("Neustadt-Süd", ["severinstr", "chlodwigplatz", "vringsveedel", "südstadt"]),
    "Severinsviertel": ("Altstadt-Süd", ["severinstr", "severinstor", "vringsveedel"]),
    "Vringsveedel": ("Altstadt-Süd", ["severinstr", "severinstor", "vringsveedel"]),
    "Agnesviertel": ("Neustadt-Nord", ["st. agnes", "agnesviertel", "sudermanplatz"]),
    "Kunibertsviertel": ("Altstadt-Nord", ["st. kunibert", "kunibertsviertel", "kaygasse"]),
    "Eigelstein": ("Neustadt-Nord", ["eigelstein", "ebertplatz", "eigelsteintor"]),
    "Kwartier Latäng": ("Neustadt-Süd", ["kwartier lataeng", "zulpicher platz", "studentenviertel"]),
    "Belgisches Viertel": ("Neustadt-Nord", ["belgisches viertel", "brusseler str", "brusseler platz", "antwerpener str"]),
    "Friesenviertel": ("Altstadt-Nord", ["friesenplatz", "friesenstr", "friesenviertel"]),
    "Rathenauviertel": ("Neustadt-Süd", ["rathenauplatz", "rathenauviertel"]),
    "Rheinauhafen": ("Altstadt-Süd", ["rheinauhafen", "schokoladenmuseum", "kranhaus"]),
    "Mediapark": ("Neustadt-Nord", ["mediapark", "cinedom"]),
    "Univiertel": ("Neustadt-Süd", ["universitat zu koln", "hauptgebaude", "albertus-magnus-platz"]),
    "Clouth": ("Nippes", ["clouth", "clouth-quartier", "xantener str"]),
    "Schanzenviertel": ("Mülheim", ["schanzenviertel", "carlswerk", "schaufenstr"]),
    "Rheinauhafen Süd": ("Altstadt-Süd", ["rheinauhafen"]),
    "KölnTriangle": ("Deutz", ["koelntriangle", "triangle"]),
    "Deutzer Hafen": ("Deutz", ["deutzer hafen"]),
    "Kölnberg": ("Meschenich", ["koelnberg"]),
    "Blumenberg-Süd": ("Blumenberg", []),
    "Lentpark": ("Bilderstöckchen", ["lentpark", "robert-perthel-str"]),
}

# --------------------------------------------------------------------------
# Sehenswürdigkeiten / Straßen je Stadtteil – liefern schwächere, aber echte
# Veedel-Treffer (z. B. „Keupstraße" -> Mülheim).
# --------------------------------------------------------------------------
LANDMARKS: dict[str, list[str]] = {
    "Altstadt-Nord": ["dom", "hauptbahnhof", "roncalliplatz", "breite str", "hohe str", "neumarkt", "hohenzollernbrucke", "wallraf"],
    "Altstadt-Süd": ["severinstr", "waidmarkt", "lutherkirche", "heumarkt", "gurtel", "schokoladenmuseum"],
    "Neustadt-Nord": ["friesenplatz", "hohenzollernring", "kaiser-wilhelm-ring", "bismarckstr", "christophstr", "gerling"],
    "Neustadt-Süd": ["zulpicher platz", "barbarossaplatz", "rudolfplatz", "hohenstaufenring", "volksgarten", "sachsenring"],
    "Deutz": ["lanxess arena", "deutzer freiheit", "rheinpark", "messe koeln", "th koln", "koelntriangle", "ottoplatz", "deutzer brucke", "tanzbrunnen", "koelnmesse"],
    "Ehrenfeld": ["venloer str", "heliosstr", "zentralmoschee", "neptunplatz", "kornerstr", "subbelrather str", "ehrenfeldgurtel", "bahnhof ehrenfeld", "cinenova", "bueze ehrenfeld", "lichtstr"],
    "Neuehrenfeld": ["landmannstr", "herkulesstr", "nussbaumerstr", "parkgurtel"],
    "Bickendorf": ["akazienweg", "rosenhof", "vogelsanger str"],
    "Vogelsang": ["vogelsanger str", "butzweilerstr"],
    "Ossendorf": ["butzweilerhof", "ossendorfer str", "mathias-bruggen-str"],
    "Bocklemünd/Mengenich": ["bocklemuend", "mengenich", "gorestr"],
    "Nippes": ["neusser str", "wilhelmplatz", "clouth", "altenberger hof", "nippeser taelchen", "blauer abend", "xantener str"],
    "Bilderstöckchen": ["escher str", "robert-perthel-str", "geldernstr"],
    "Riehl": ["zoo koeln", "flora", "riehler str", "seniorenzentrum", "stammheimer str"],
    "Niehl": ["ford", "industriestr", "geestemunder str", "niehler hafen", "feldgartenstr"],
    "Longerich": ["militarringstr", "longericher str", "friedhof longerich"],
    "Mauenheim": ["mauenheimer str", "nibelungenstr"],
    "Weidenpesch": ["pferderennbahn", "galopprennbahn", "scheibenstr", "schlesischer platz", "neusser str"],
    "Sülz": ["suelzgurtel", "suelzburgstr", "berrenrather str", "weyerthalstr", "klopstockstr"],
    "Klettenberg": ["klettenbergpark", "siebengebirgsallee", "klettenberggurtel"],
    "Lindenthal": ["durener str", "stadtwald", "lindenthalgurtel", "uniklinik", "kerpener str", "gleueler str"],
    "Braunsfeld": ["aachener str", "braunsfelder str", "clarenbachstr"],
    "Müngersdorf": ["rheinenergiestadion", "sportpark mungersdorf", "stadion", "jungersdorfer str"],
    "Junkersdorf": ["junkersdorfer str", "horbeller str"],
    "Weiden": ["weidener str", "bocklemunder str"],
    "Lövenich": ["loevenicher str", "brauweilerstr"],
    "Widdersdorf": ["widdersdorfer str", "jakob-str"],
    "Bayenthal": ["bonner str", "bayenthalgurtel", "goltsteinstr"],
    "Marienburg": ["marienburger str", "parkallee", "bonner str"],
    "Zollstock": ["gottesweg", "vorgebirgspark", "zollstockgurtel", "pohligstr"],
    "Raderberg": ["bruckenstr", "raderberggurtel"],
    "Raderthal": ["raderthalgurtel", "markusstr"],
    "Rodenkirchen": ["maternusplatz", "rheinbogen", "hauptstr", "ringstr"],
    "Weiß": ["weisser str", "rheinbogen", "godorfer str"],
    "Sürth": ["surther str", "rheinbogen"],
    "Godorf": ["godorfer hafen", "godorfer str", "industriepark"],
    "Meschenich": ["koelnberg", "meschenicher str", "bruhler str"],
    "Immendorf": ["immendorfer str"],
    "Rondorf": ["rondorfer str", "hochkirchen"],
    "Hahnwald": ["hahnwald", "friedrich-ebert-str"],
    "Mülheim": ["keupstr", "mulheimer brucke", "wiener platz", "carlswerk", "schanzenviertel", "muhlheimer str", "genovevastr", "buchheimer str"],
    "Buchheim": ["buchheimer str", "herler str"],
    "Buchforst": ["waldecker str", "kopernikusstr"],
    "Dellbrück": ["dellbrucker hauptstr", "hohenfelder see", "thurner hof", "mielenchriststr"],
    "Holweide": ["holweider str", "neufelder str"],
    "Höhenhaus": ["hohenhauser str", "amsterdamer str"],
    "Dünnwald": ["dunnwalder str", "wildpark", "schlebuscher str"],
    "Flittard": ["flittarder str", "stammheimer str", "bayer"],
    "Stammheim": ["stammheimer str", "hoferstr"],
    "Kalk": ["kalker hauptstr", "vietorstr", "koeln arcaden", "gremberger str", "humboldtstr", "kalk-mitte", "trimbornstr"],
    "Höhenberg": ["hohenberger str", "frankfurter str", "merheimer heide"],
    "Humboldt/Gremberg": ["humboldtstr", "gremberg", "vinzenzstr"],
    "Vingst": ["vingster ring", "ostheimer str"],
    "Ostheim": ["ostheimer str", "gremberger str"],
    "Merheim": ["merheimer str", "broicher str"],
    "Brück": ["olpererstr", "bruck", "gummersbacher str"],
    "Neubrück": ["neubrucker str", "amsterdamer str"],
    "Rath/Heumar": ["rather str", "heumar", "gremberger str"],
    "Porz": ["porzer rathaus", "friedrich-ebert-platz", "hauptstr", "bahnhof porz"],
    "Poll": ["poller wiesen", "siegriedstr", "poll-vingster-str", "rollberg"],
    "Westhoven": ["westhoven", "berliner str"],
    "Ensen": ["enser str", "gilgaustr"],
    "Gremberghoven": ["gremberghoven", "frankfurter str"],
    "Eil": ["eiler str", "heumarer str"],
    "Urbach": ["urbacher str", "waldbahnstr"],
    "Elsdorf": ["elsdorfer str"],
    "Finkenberg": ["finkenberg", "dahnstr"],
    "Zündorf": ["groov", "zundorfer str", "hauptstr", "yachthafen"],
    "Langel": ["langeler str", "rheinbogen"],
    "Libur": ["libur", "wiesenstr"],
    "Lind": ["linder str", "linder kreuz"],
    "Wahn": ["flughafen koeln/bonn", "wahn", "junkerstr", "airport"],
    "Wahnheide": ["wahnheide", "flugplatzstr", "schanzenstr"],
    "Grengel": ["grengel", "mauserstr"],
    "Chorweiler": ["liverpooler platz", "chorweiler zentrum", "city-center", "athener str", "pariser str"],
    "Fühlingen": ["fuhlinger see", "regattabahn", "blackfield"],
    "Worringen": ["worringen", "brechtener str", "dorfstr"],
    "Pesch": ["pescher str", "donatusstr"],
    "Esch/Auweiler": ["esch", "auweiler", "st.-martin-str"],
    "Heimersdorf": ["heimersdorf", "haselbergstr"],
    "Lindweiler": ["lindweiler", "marienbergstr"],
    "Blumenberg": ["blumenberg", "wachtelstr"],
    "Merkenich": ["merkenich", "frohsinnstr"],
    "Seeberg": ["seeberg", "stelzestr"],
    "Volkhoven/Weiler": ["volkhoven", "weiler", "geislerstr"],
    "Roggendorf/Thenhoven": ["roggendorf", "thenhoven", "schleifenstr"],
}

# --------------------------------------------------------------------------
# KSTA-Regionen (für Eingaben außerhalb Kölns)
# --------------------------------------------------------------------------
REGIONEN: dict[str, str] = {
    "Bonn": "rhein-sieg-bonn",
    "Rhein-Sieg": "rhein-sieg-bonn",
    "Leverkusen": "leverkusen",
    "Rhein-Erft": "rhein-erft",
    "Rhein-Berg": "rhein-berg",
    "Oberberg": "oberberg",
    "Euskirchen": "euskirchen-eifel",
}

# Umland & andere Städte: Meldungen von dort haben in einem Kölner
# Veedel-Stream nichts zu suchen (das Polizei-Feed der Behörde Köln berichtet
# z. B. auch aus Leverkusen). Namen wie „Bonn", „Neuss" oder „Essen" fehlen
# bewusst – „Bonner Straße" und „Neusser Straße" sind Kölner Straßen.
NACHBARSTAEDTE = [
    "Leverkusen", "Bergisch Gladbach", "Frechen", "Hürth", "Brühl", "Pulheim",
    "Dormagen", "Monheim", "Langenfeld", "Wesseling", "Troisdorf",
    "Niederkassel", "Bornheim", "Erftstadt", "Kerpen", "Düren", "Siegburg",
    "Aachen", "Düsseldorf", "Duisburg", "Oberhausen", "Gelsenkirchen",
    "Dortmund", "Bochum", "Wuppertal", "Solingen", "Remscheid", "Münster",
    "Hamburg", "Berlin", "München", "Frankfurt", "Stuttgart", "Hannover",
    "Bremen", "Leipzig", "Dresden", "Kassel", "Osnabrück",
]

# Städte, für die wir wenigstens ein kleines Grundprofil anbieten
# (Name -> (Bundesland, Liste bekannter Veedel/Stadtteile als Stichworte)).
ANDERE_STAEDTE: dict[str, list[str]] = {
    "Berlin": [], "Hamburg": [], "München": [], "Muenchen": [], "Frankfurt": [],
    "Düsseldorf": [], "Duesseldorf": [], "Stuttgart": [], "Leipzig": [],
    "Dresden": [], "Hannover": [], "Bremen": [], "Essen": [], "Dortmund": [],
    "Bochum": [], "Wuppertal": [], "Aachen": [], "Mönchengladbach": [],
    "Moenchengladbach": [], "Bonn": [], "Leverkusen": [],
}


@dataclass
class Place:
    """Ein aufgelöster Suchbegriff."""

    query: str
    kind: str                                   # stadtteil|bezirk|veedel|region|stadt|unbekannt
    name: str                                   # kanonischer Anzeigename
    city: str = CITY
    bezirk: str | None = None
    bezirk_slug: str | None = None
    stadtteile: list[str] = field(default_factory=list)
    slugs: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    mehrdeutig: bool = False
    region_slug: str | None = None

    # -- Anzeigetexte -----------------------------------------------------
    @property
    def label(self) -> str:
        if self.kind == "stadtteil":
            return f"{self.name} · Bezirk {self.bezirk}"
        if self.kind == "bezirk":
            return f"Bezirk {self.name}"
        if self.kind == "veedel":
            off = "/".join(self.stadtteile) or self.name
            return f"{self.name} · Veedel in {off}"
        if self.kind == "region":
            return f"Region {self.name}"
        if self.kind == "stadt":
            return self.name
        return self.query or CITY

    @property
    def headline(self) -> str:
        if self.kind == "stadtteil":
            return f"Köln-{self.name}"
        if self.kind == "bezirk":
            return f"Köln · Bezirk {self.name}"
        if self.kind == "veedel":
            return f"{self.name}"
        if self.kind == "region":
            return f"{self.name}"
        if self.kind == "stadt":
            return self.name
        return self.query or CITY


# --------------------------------------------------------------------------
# Lookup-Tabellen (werden einmalig gebaut)
# --------------------------------------------------------------------------
def _build_lookups() -> dict[str, tuple[str, str]]:
    """normierter Name -> (kanonischer Name, Typ)."""
    lut: dict[str, tuple[str, str]] = {}

    for bez, slug_ in BEZIRKE.items():
        lut[slug(bez)] = (bez, "bezirk")
        lut[slug(f"koeln {bez}")] = (bez, "bezirk")
        lut[slug(f"bezirk {bez}")] = (bez, "bezirk")

    for bez, sts in STADTTEILE.items():
        for st in sts:
            key = slug(st)
            lut[key] = (st, "stadtteil")
            lut[slug(f"koeln {st}")] = (st, "stadtteil")
            lut[slug(f"koeln-{st}")] = (st, "stadtteil")
            # getrennt geschriebene Varianten: „Bocklemünd Mengenich"
            if "/" in st:
                for teil in st.split("/"):
                    lut.setdefault(slug(teil), (st, "stadtteil"))
                    lut.setdefault(slug(f"koeln {teil}"), (st, "stadtteil"))
            if "-" in st:
                for teil in st.split("-"):
                    if len(teil) > 3:
                        lut.setdefault(slug(teil), (st, "stadtteil"))

    for ved, (st, _) in VEEDEL.items():
        lut[slug(ved)] = (ved, "veedel")
        lut[slug(f"koeln {ved}")] = (ved, "veedel")

    for region in REGIONEN:
        lut[slug(region)] = (region, "region")

    lut[slug("koeln")] = (CITY, "stadt")
    lut[slug("cologne")] = (CITY, "stadt")
    lut[slug("koeln stadt")] = (CITY, "stadt")
    return lut


_LUT = _build_lookups()

# Alle Veedel-Namen für die Autovervollständigung der Oberfläche
_ALLE_ORTSNAMEN: list[str] = sorted(
    {bez for bez in BEZIRKE}
    | {st for sts in STADTTEILE.values() for st in sts}
    | set(VEEDEL),
    key=lambda s: (slug(s) < "a", slug(s)),
)


def ortsliste() -> list[dict]:
    """Liste aller Orte für die Autovervollständigung (nach Bezirk gruppiert)."""
    out = []
    for bez, sts in STADTTEILE.items():
        for st in sts:
            out.append({"name": st, "bezirk": bez, "typ": "Stadtteil"})
    for ved, (st, _) in VEEDEL.items():
        out.append({
            "name": ved,
            "bezirk": STADTTEIL_BEZIRK.get(st, "Innenstadt"),
            "typ": "Veedel",
        })
    return out


def _keywords_for(stadtteile: list[str], extra: list[str] | None = None) -> list[str]:
    """Suchbegriffe: Namen + Sehenswürdigkeiten, ohne Duplikate."""
    kws: list[str] = []
    for st in stadtteile:
        kws.append(norm(st))
        for teil in re.split(r"[/\-]", st):
            if len(teil) > 3:
                kws.append(norm(teil))
        for lm in LANDMARKS.get(st, []):
            kws.append(norm(lm))
    for e in extra or []:
        kws.append(norm(e))
    seen, uniq = set(), []
    for k in kws:
        k = k.strip()
        if k and k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq


def _slugs_for(stadtteile: list[str], bezirk_slug: str | None) -> list[str]:
    """Kandidaten für KSTA-Stadtteilfeeds.

    Verifiziert: ``/feed/rss/koeln/koelner-innenstadt/deutz/index.rss`` und
    ``/feed/rss/koeln/nippes/bilderstoeckchen/index.rss``. Wenn der Stadtteil
    wie der Bezirk heißt, hängt KSTA ``-veedel`` an (z. B. Nippes ->
    ``nippes/nippes-veedel``). Beide Varianten werden geliefert, die
    Quellenlogik probiert sie aus und merkt sich, welche funktioniert.
    """
    out: list[str] = []
    for st in stadtteile:
        s = slug(st)
        if s and s not in out:
            out.append(s)
        if bezirk_slug and s == bezirk_slug:
            v = f"{s}-veedel"
            if v not in out:
                out.insert(0, v)
        elif bezirk_slug and st in BEZIRKE:
            out.insert(0, f"{s}-veedel")
    return out


def resolve_place(query: str) -> Place:
    """Macht aus einer freien Texteingabe einen :class:`Place`."""
    raw = (query or "").strip()
    if not raw:
        raw = CITY
    key = slug(raw)

    # „Köln-Ehrenfeld", „Ehrenfeld Köln", „Veedel Ehrenfeld" …
    for prefix in ("koeln ", "koeln-", "cologne ", "cologne-", "veedel ", "stadtteil "):
        if key.startswith(prefix.strip().replace("-", " ")):
            rest = key[len(prefix.strip().replace("-", " ")):].strip(" -")
            if rest in _LUT:
                key = rest
                break
    if key.endswith(" koeln"):
        key = key[: -len(" koeln")]

    hit = _LUT.get(key)

    if hit is None:
        # unscharf: Tippfehler/Teilwort (z. B. „ehrenfeldt", „sülz köln")
        for candidate in _LUT:
            if candidate.startswith(key) or key.startswith(candidate):
                if min(len(candidate), len(key)) >= 4:
                    hit = _LUT[candidate]
                    break

    if hit is None:
        # andere Stadt?
        for stadt in ANDERE_STAEDTE:
            if key == slug(stadt):
                return Place(query=raw, kind="stadt", name=stadt, city=stadt)
        # Unbekanntes Wort: wir bleiben bei Köln und melden das in der UI.
        return Place(query=raw, kind="unbekannt", name=raw, city=CITY)

    name, kind = hit

    if kind == "stadt":
        return Place(
            query=raw, kind="stadt", name=CITY, city=CITY,
            slugs=[], keywords=[norm(CITY), "koeln", "cologne"],
        )

    if kind == "region":
        return Place(
            query=raw, kind="region", name=name, city=name,
            region_slug=REGIONEN[name], keywords=[norm(name)],
        )

    if kind == "bezirk":
        sts = STADTTEILE[name]
        return Place(
            query=raw, kind="bezirk", name=name, bezirk=name,
            bezirk_slug=BEZIRKE[name], stadtteile=list(sts),
            slugs=_slugs_for(sts, BEZIRKE[name]),
            keywords=_keywords_for(sts, [norm(name)]),
            mehrdeutig=slug(name) in MEHRDEUTIG,
        )

    if kind == "veedel":
        st, extra = VEEDEL[name]
        bez = STADTTEIL_BEZIRK.get(st, "Innenstadt")
        return Place(
            query=raw, kind="veedel", name=name,
            bezirk=bez, bezirk_slug=BEZIRKE[bez], stadtteile=[st],
            slugs=_slugs_for([st], BEZIRKE[bez]),
            keywords=_keywords_for([st], extra + [norm(name)]),
            mehrdeutig=slug(st) in MEHRDEUTIG,
        )

    # Stadtteil
    bez = STADTTEIL_BEZIRK[name]
    return Place(
        query=raw, kind="stadtteil", name=name,
        bezirk=bez, bezirk_slug=BEZIRKE[bez], stadtteile=[name],
        slugs=_slugs_for([name], BEZIRKE[bez]),
        keywords=_keywords_for([name], []),
        mehrdeutig=slug(name) in MEHRDEUTIG,
    )


def benachbarte_stadtteile(place: Place, limit: int = 8) -> list[str]:
    """Stadtteile im selben Bezirk – für die „Auch interessant"-Leiste."""
    if not place.bezirk:
        return []
    same = [st for st in STADTTEILE[place.bezirk] if st not in place.stadtteile]
    return same[:limit]
