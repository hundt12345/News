# Lokal-Radar Köln 📍

Nachrichten **für ein bestimmtes Veedel** – nicht für irgendeins.

Eine Flask-App, die die lokalen Quellen von Köln (Redaktionen, Polizei, Stadt,
Foren) parallel abfragt, jede Meldung einem Stadtteil/Veedel zuordnet und das
Ergebnis in zwei Sichten anzeigt: **nach Ort** (Veedel → Bezirk → Stadt) und
**nach Thema** (Blaulicht, Verkehr, Politik, Kultur, Sport, Wohnen, Foren, Veedel).

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py                                       # http://localhost:5000
```

Ohne Internetzugang im Testbetrieb: `python app.py` mit `NEWS_DEMO=1` oder
`http://localhost:5000/?ort=Nippes&demo=1` – dann werden die **originalen**,
am 13.10.2026 gespeicherten Feeds aus `tests/fixtures/` verwendet.

---

## Was diese Version repariert

Die App lief vorher, hatte aber drei greifbare Fehler. Alle drei sind behoben
und durch Offline-Tests abgesichert (`tests/test_local.py`, 49 Tests).

### 1. „Reddit lädt nicht" ✅

**Ursache:** `_robots_ok()` las `robots.txt` ohne User-Agent. Reddit antwortet
darauf mit `403`, der Parser setzte `disallow_all = True`, und die Quelle wurde
**stillschweigend übersprungen** – im Protokoll stand nur „0 Artikel".

**Jetzt:**

* `robots_ok()` fragt mit echtem Browser-User-Agent an, merkt sich das Ergebnis
  pro Host und **fällt bei einem Fehler auf „erlaubt" zurück** (ein 403 auf
  `robots.txt` ist kein Verbot).
* Reddit bekommt eine **Endpoint-Kaskade**: OAuth-API (wenn `REDDIT_CLIENT_ID`
  und `REDDIT_CLIENT_SECRET` gesetzt sind) → `www.reddit.com/.json` →
  `old.reddit.com/.json` → `.rss` → optionaler Spiegel `REDDIT_MIRROR`.
* `/r/*/search` wird bewusst **nicht** benutzt (laut `robots.txt` gesperrt);
  stattdessen `/r/Koeln/new`, `/r/cologne/new` plus lokale Filterung.
* Schlägt alles fehl, steht der Grund jetzt **sichtbar** im Quellen-Protokoll
  und in den Warnungen – und ein letzter guter Cache-Stand (≤ 24 h) wird mit
  dem Hinweis „Letzter guter Stand (…)" weiter angezeigt.

### 2. „Stadtteil-Suche liefert falsche Bezirke, immer dieselben Artikel" ✅

**Ursache:** die Quellenliste war statisch auf Deutz verdrahtet, dazu kamen
stadtunabhängige Subreddits (`r/de`, `r/worldnews`). Der Ortsfilter war ein
einfaches `if name in text` über Titel **und** URL, ohne Reihenfolge: Ein
Artikel aus Weidenpesch, dessen URL `/koeln/nippes/weidenpesch/…` lautet,
enthielt das Wort „nippes" – und wurde als Veedel-Treffer für Nippes gewertet.

**Jetzt** (`news/places.py` + `news/relevance.py`):

* **Voller Ortsdatensatz:** 86 offizielle Stadtteile, 9 Bezirke, 21 kölsche
  Veedel (Südstadt, Agnesviertel, Kwartier Latäng, Clouth, Kölnberg …),
  Straßen und Sehenswürdigkeiten je Veedel, 39 Nachbarstädte.
* **Der Quellenplan wird aus dem Ort gebaut** (`build_plan`): Stadtteil-Feeds
  der KSTA (inkl. Slug-Varianten wie `nippes-veedel`), der Bezirksfeed,
  stadtweite Feeds, Sport, Foren. Für Bonn/Düsseldorf gibt es ein eigenes Profil.
* **Orts-Matching als Rangfolge mit frühem Ausstieg** – der entscheidende Punkt
  ist, dass die **Position in der URL** stärker wiegt als ein Wortfund:

  | Rang | Beleg | Punkte | Ergebnis |
  |---|---|---|---|
  | 1 | eigenes Veedel als **eigenes Pfadsegment** der KSTA-URL | 100 | Veedel |
  | 2 | eigener Slug im Artikel-Slug (nicht bei KSTA-Pfaden) | 90 | Veedel |
  | 2b | KSTA hat den Artikel **einem anderen Veedel** zugeordnet | 50 / 0 | Nachbarveedel bzw. **verworfen** |
  | 3 | Ortsname oder Adjektivform im Text („Nippeser", „Kölner") | 85 / 78 | Veedel |
  | 4 | Straße oder Sehenswürdigkeit des Veedels | 62 | Veedel |
  | 5 | Meldung spielt in einem anderen Veedel | 50 / **0** | Nachbarveedel bzw. verworfen |
  | 6 | Bezirk (URL-Segment, Slug oder Name) | 48–50 | Bezirk |
  | 7 | Köln-Bezug im Text | 12 | Stadt |
  | 8 | offizielle Meldung von Stadt/Polizei bzw. Köln-Kanal | 12 | Stadt |

  Meldungen aus einem **anderen Bezirk** oder einer **anderen Stadt**
  („Leverkusenerin verliert Zähne …", „Wetter in Hamburg …") werden verworfen
  und tauchen nirgends mehr auf.
* **Falsche Freunde entschärft:** Behördenphrasen („Polizei Köln") zählen nicht
  als Ortsbeleg, „Bezirk Nippes" und „BV Nippes" zählen nicht als Veedel-Nippes,
  mehrdeutige Namen (Poll, Kalk, Lind, Weiß, Esch, Wahn, Seeberg, Deutz) brauchen
  einen zusätzlichen Köln-Beleg, und Adjektive wie „weisse"/„linder" werden nicht
  als Stadtteil gedeutet.
* **Deterministisch:** Die Quellen werden in Plan-Reihefolge ausgewertet, nicht
  in der Reihenfolge ihrer Netzwerk-Antwort. Früher entschied der Zufall, welche
  Dublette überlebt.
* **Dubletten-Erkennung** über Dachzeilen („Fusion Cologne: …" vs. „…"), über
  die ersten vier signifikanten Wörter und über Ähnlichkeit; zusammengeführte
  Meldungen zeigen „auch bei: …".

### 3. „News besser aufteilen" ✅

Die alte Gruppierung teilte nach dem **ersten Wort der Überschrift** – deshalb
hieß eine Gruppe „Die" und eine andere „Köln".

**Jetzt zwei Sichten über dieselbe Datenbasis:**

* **Nach Ort:** `Veedel` (immer zuerst, auch wenn leer – dann mit Erklärung),
  `Bezirk <Name>`, `Köln gesamt`. Bei einer Stadt-Anfrage gibt es genau eine
  Liste, bei einer Bezirks-Anfrage die Stadtteile des Bezirks.
* **Nach Thema:** Blaulicht 🚨, Verkehr & Bau 🚋, Politik & Stadt 🏛️,
  Kultur & Karneval 🎭, Sport ⚽, Wohnen & Wirtschaft 🏗️,
  Foren & Community 💬, Veedel 🏘️ – mit Themen-Chips zum Umschalten.
* Zusätzlich je Meldung: **Warum?** – der Beleg, der zur Einordnung geführt hat
  („URL-Pfad „nippes-veedel"", „Nachbarveedel Weidenpesch (URL)",
  „Ort „neusser str""). Plus Quellen-Protokoll mit Status, Artikelzahl, Dauer
  und Weg jeder Quelle.

### 4. Neu: relevante Foren & Community für Köln ✅

Als eigene Quellenart (`group="foren"`, Kategorie „Foren & Community", per
Chip abschaltbar):

* **Reddit** `r/Koeln` und `r/cologne` (`/new`), lokal nach Köln-Bezug gefiltert.
* **KOELN·0221** – Kölner Stadtportal (kein RSS, wird als HTML gelesen).
* **koeln.de Lokalnews** – offizielles Stadtportal.
* **Veedel-Blogs**: `VEEDEL_BLOGS` in `news/sources.py` (Stadtteil-Slug →
  Name + Feed-URL). Bewusst leer: der bekannte Ehrenfeld-Blog ist 2019
  eingeschlafen. Eigene aktive Blogs einfach eintragen.
* Foren-Posts ohne Ortsnennung bleiben als stadtweit relevant stehen
  (Beleg „aus dem Köln-Forum"), Posts über andere Veedel/Städte fliegen raus.

---

## Quellen

| Quelle | Art | Was geholt wird |
|---|---|---|
| KSTA / Kölner Stadt-Anzeiger | Redaktion | Stadtteil-Feeds `koeln/{bezirk}/{stadtteil}/index.rss`, Bezirksfeeds, Ressorts, Sport |
| Kölnische Rundschau | Redaktion | `koeln/`, `region/`, Sport (FC, Haie) |
| EXPRESS | Redaktion | `koeln/index.rss` |
| Polizei Köln (Presseportal NRW) | Behörde | Blaulicht-Feed der Behörde (Region 14570) |
| Stadt Köln | Behörde | Pressemeldungen |
| koeln.de | Portal | Lokalnews-Feed |
| Reddit r/Koeln, r/cologne | Forum | `/new`, lokal gefiltert |
| KOELN·0221 | Forum | Stadtportal als HTML |

Geprüft und **nicht** aufgenommen: `koeln-forum.de` (kein Feed), KVB (keine RSS,
nur Webseite/Mastodon), Radio Köln via nrwision (Podcast, keine News),
domradio (Cookie-Wall), `presseportal.de/rss/blaulicht/nr/12415` (404).

Alle Feed-Adressen stehen in `news/sources.py`; neue Quellen = eine Zeile
`SourceSpec(...)` mit `scope` (`veedel` / `bezirk` / `koeln` / `region`) und
`group` (`medien` / `behoerden` / `sport` / `foren`).

---

## HTTP-Schnittstelle

| Route | Rückgabe |
|---|---|
| `GET /?ort=Nippes&themen=medien,foren` | Seite (HTML) |
| `GET /api/news?ort=…&themen=…&fmt=html` | genau dasselbe Fragment – so aktualisiert die Oberfläche ohne Reload |
| `GET /api/news?ort=…&fmt=json` | `daten` als JSON (`Cache-Control: no-store`) |
| `GET /api/orte?q=nip` | Ortstreffer für die Autovervollständigung |
| `GET /api/quellen?ort=Nippes` | der berechnete Quellenplan |
| `GET /health` | `{"status":"ok"}` |

Parameter: `ort`, `themen` (Kommaliste aus `medien`, `behoerden`, `sport`,
`foren`), `refresh=1` (Cache ignorieren), `demo=1`, `fmt=html|json`.

Payload (JSON):

```jsonc
{
  "place": {
    "name": "Nippes", "bezirk": "Nippes", "kind": "stadtteil",   // stadtteil|veedel|bezirk|stadt|region|unbekannt
    "label": "Nippes · Bezirk Nippes", "headline": "Nippes",
    "slug": "nippes", "city": "Köln", "query": "Nippes",
    "stadtteile": [...], "nachbarn": ["Bilderstöckchen", "Longerich", ...]
  },
  "sections":   [ { "key": "veedel", "label": "Nippes", "hinweis": "...", "artikel": [ ... ] } ],
  "categories": { "blaulicht": { "label": "Blaulicht", "artikel": [ ... ] } },
  "top_themen": { "politik": 4, "blaulicht": 3, ... },
  "themen":     { "medien": true, "behoerden": true, "sport": true, "foren": true },
  "sources":    [ { "name": "...", "ok": true, "count": 7, "seconds": 0.42,
                    "group": "medien", "used": "RSS", "error": "", "hint": "" } ],
  "stats":      { "artikel_roh": 44, "artikel_behalten": 15, "artikel_zu_alt": 0,
                  "veedel_treffer": 3, "bezirk_treffer": 6,
                  "quellen_ok": 14, "quellen_gesamt": 14, "quellen_fehler": 0,
                  "neuester_artikel": "...", "aeltester_artikel": "..." },
  "warnungen":  [...], "wetter": {...},
  "demo": false, "duration_s": 0.07, "generated_at": "..."
}
```

Ein einzelner Artikel: `title`, `link`, `source`, `published`, `age_minutes`,
`teaser`, `author`, `image`, `kind`, `scope` (`veedel|bezirk|koeln|region`),
`category`, `score`, `evidence` (die Belege der Einordnung), `also_from`
(weitere Redaktionen mit derselben Meldung).

`crawler.crawl_for_city(ort)` – der Kompatibilitätsshim für alte Aufrufe –
liefert daraus `{"stream": [...], "summary": {kategorie: [...]}, "raw": daten}`.

> Achtung beim Weiterbauen: Der Schlüssel heißt `artikel`, **nicht** `items`.
> In Jinja liefert `abschnitt.items` sonst die gleichnamige Dict-Methode
> (`TypeError: object of type 'builtin_function_or_method' has no len()`).

---

## Umgebungsvariablen

| Variable | Standard | Wirkung |
|---|---|---|
| `PORT` | `5000` | Port des Flask-Servers |
| `NEWS_DEMO` | `0` | `1` = gespeicherte Original-Feeds statt Live-Abruf |
| `NEWS_CACHE_DIR` | `cache` | Verzeichnis für den Quellen-Cache |
| `NEWS_SOURCE_TTL` | `300` | Sekunden, bevor eine Quelle neu geholt wird |
| `NEWS_STALE_MAX_AGE` | `86400` | so lange darf ein letzter guter Stand verwendet werden |
| `NEWS_MAX_ALTER_TAGE` | `60` | Meldungen, die älter sind, werden verworfen |
| `NEWS_MAX_WORKERS` | `8` | parallele Abrufe |
| `OWM_API_KEY` | – | Wetter über OpenWeatherMap; **ohne** Key wird Open-Meteo genutzt, ohne Key und ohne Antwort verschwindet das Wetter-Widget |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | – | eigene Reddit-App → deutlich höhere Limits |
| `REDDIT_MIRROR` | – | Ausweich-Host, falls `reddit.com` blockt |
| `FLASK_DEBUG` | `0` | `1` = Debug-Modus (nicht im Produktivbetrieb) |

---

## Tests

```bash
python -m unittest discover -s tests -t .      # 49 Tests, kein Netzwerk nötig
```

Die Tests laufen komplett offline: `NEWS_DEMO=1`-Pfad bzw. gespeicherte Feeds
in `tests/fixtures/` (echte Antworten von ksta.de, express.de,
koeln.polizei.nrw, stadt-koeln.de und reddit.com). Abgeprüft werden u. a.:

* Nippes bekommt Nippes – und **nicht** Weidenpesch/Niehl/Bilderstöckchen
* Bilderstöckchen bekommt nur sein eigenes Veedel
* Deutz (Bezirk Innenstadt) und Zollstock (Bezirk Rodenkirchen) korrekt getrennt
* URL-Position schlägt Wortfund (`/koeln/nippes/weidenpesch/…` ≠ Veedel Nippes)
* Leverkusen und Hamburg werden verworfen, „Bonner Straße"/„Neusser Straße" nicht
* Dachzeilen-Dubletten werden zusammengeführt
* mehrdeutige Namen brauchen einen Köln-Beleg
* Abschnitte, Kategorien, API-JSON, API-HTML-Fragment, `/health`, `/api/orte`

---

## Aufbau

```
app.py                  Flask-Routen, Themen-Chips, Autovervollständigung
crawler.py              Kompatibilitätsshim (crawl_for_city) für alte Aufrufe
news/
  places.py             Ortsdatensatz: 86 Stadtteile, 9 Bezirke, 21 Veedel,
                        Straßen/Sehenswürdigkeiten, Nachbarstädte, Slug-LUT
  sources.py            Quellenregistry + build_plan(ort, themen)
  fetch.py              HTTP, robots.txt, RSS/Atom/JSON/HTML, Reddit-Kaskade, Cache
  relevance.py          Orts-Matching, Punktwerte, Kategorien, Dedupe, Sortierung
  aggregator.py         orchestriert alles und baut die Antwort
  weather.py            OpenWeatherMap → Open-Meteo → ausblenden
  demo.py               gespeicherte Feeds statt Netzwerk
templates/              index.html + partials/results.html + partials/_macros.html
static/                 style.css, app.js (kein Build-Schritt)
tests/                  49 Offline-Tests + fixtures/
```

**Caching:** Jede Quelle landet einzeln in `cache/quellen.json`
(`NEWS_SOURCE_TTL` = 300 s). Ist eine Quelle down, wird bis zu
`NEWS_STALE_MAX_AGE` der letzte gute Stand gezeigt – gekennzeichnet als
„Letzter guter Stand (…)". `?refresh=1` erzwingt einen neuen Abruf.

---

## Deployment (render.com)

`render.yaml` liegt bei: neues Web Service anlegen, Repo verbinden, fertig.
Der Health-Check läuft gegen `/health`. `PORT` wird von Render gesetzt;
`app.py` bindet auf `0.0.0.0`.

Für andere Hoster: `pip install -r requirements.txt`, dann
`gunicorn -b 0.0.0.0:$PORT 'app:app'` (Gunicorn ist bewusst keine harte
Abhängigkeit, `python app.py` läuft ebenfalls).
