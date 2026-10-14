# -*- coding: utf-8 -*-
"""HTTP-Layer: höflich, robust und mit brauchbarer Fehlerdiagnose.

Warum Reddit vorher nie geladen hat
------------------------------------
1. ``feedparser.parse(url)`` schickt seinen eigenen User-Agent
   (``feedparser/6.x +https://...``). Reddit antwortet darauf mit **403**.
2. ``_robots_ok()`` holte ``robots.txt`` mit ``urllib`` und dem Default-UA
   ``Python-urllib/3.x``. Auch das blockt Reddit (403) – und ein
   ``RobotFileParser`` setzt bei 403 ``disallow_all = True``.
   Ergebnis: **jede** Reddit-Quelle wurde still übersprungen.
3. Es gab weder Retry noch Fehlerausgabe – man sah einfach nur „nichts".

Gefixt durch: eine gemeinsame ``requests.Session`` mit Browser-UA,
robots.txt-Caching, eine Reddit-Endpoint-Kaskade, Retries mit Backoff
(inkl. ``Retry-After``) und einer Diagnose pro Quelle, die in der UI landet.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import threading
import time
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
    "NewsAggregator/2.0 (+https://github.com/hundt12345/News)"
)

# Requests are deliberately bounded so a slow or blocked publisher cannot keep
# the page request open indefinitely. Render can use shorter values without
# making local development as aggressive.
DEFAULT_TIMEOUT = max(0.1, float(os.environ.get("NEWS_HTTP_TIMEOUT", "9")))
MAX_RETRIES = max(0, int(os.environ.get("NEWS_HTTP_RETRIES", "2")))
ROBOTS_TIMEOUT = max(0.1, float(os.environ.get("NEWS_ROBOTS_TIMEOUT", "5")))

# optionale eigene Reddit-App (https://www.reddit.com/prefs/apps)
REDDIT_CLIENT_ID = ""
REDDIT_CLIENT_SECRET = ""
# optionaler Spiegel (z. B. eigene Redlib-Instanz), ohne Slash am Ende
REDDIT_MIRROR = ""


# --------------------------------------------------------------------------
# Datenstrukturen
# --------------------------------------------------------------------------
@dataclass
class Item:
    """Ein Nachrichten-Eintrag, unabhängig von der Quelle."""

    title: str
    link: str
    source: str
    published: datetime | None = None
    teaser: str = ""
    author: str = ""
    image: str = ""
    kind: str = "news"            # news | forum | presse | polizei
    url_slug: str = ""            # Pfadsegmente – wichtig für die Veedel-Zuordnung
    score: float = 0.0
    scope: str = "koeln"          # veedel | bezirk | koeln | region
    category: str = "veedel"
    evidence: list[str] = field(default_factory=list)
    also_from: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "link": self.link,
            "source": self.source,
            "published": self.published.isoformat() if self.published else None,
            "age_minutes": (
                round((datetime.now(timezone.utc) - self.published).total_seconds() / 60)
                if self.published else None
            ),
            "teaser": self.teaser,
            "author": self.author,
            "image": self.image,
            "kind": self.kind,
            "scope": self.scope,
            "category": self.category,
            "score": round(self.score, 1),
            "evidence": self.evidence,
            "also_from": self.also_from,
        }


@dataclass
class SourceResult:
    """Ergebnis (oder Fehler) einer einzelnen Quelle."""

    name: str
    url: str
    ok: bool
    items: list[Item] = field(default_factory=list)
    error: str = ""
    hint: str = ""
    seconds: float = 0.0
    group: str = "medien"          # medien | behörden | foren | sport
    used: str = ""                 # welcher Endpunkt tatsächlich geklappt hat

    def to_dict(self) -> dict:
        return {
            "name": self.name, "url": self.url, "ok": self.ok,
            "count": len(self.items), "error": self.error, "hint": self.hint,
            "seconds": round(self.seconds, 2), "group": self.group,
            "used": self.used,
        }


# --------------------------------------------------------------------------
# Session + robots.txt
# --------------------------------------------------------------------------
_session_local = threading.local()
_robots_cache: dict[str, tuple[bool, float]] = {}
_robots_lock = threading.Lock()
ROBOTS_TTL = 3600


def session() -> requests.Session:
    """Pro Thread eine Session – ThreadPool-tauglich, Connection-Reuse."""
    s = getattr(_session_local, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, "
                      "text/xml, application/json;q=0.9, text/html;q=0.8, */*;q=0.5",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.6",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        })
        _session_local.s = s
    return s


def robots_ok(url: str, timeout: float = ROBOTS_TIMEOUT) -> bool:
    """robots.txt-Prüfung mit Cache.

    Wichtig: Wir holen ``robots.txt`` über **dieselbe** Session (Browser-UA),
    damit Reddit & Co. nicht sofort 403 liefern. Wenn robots.txt nicht
    erreichbar ist, gilt „erlaubt" – genau wie vorher, nur eben ohne dass ein
    403 fälschlich als „alles verboten" interpretiert wird.
    """
    p = urlparse(url)
    host = f"{p.scheme}://{p.netloc}"
    now = time.time()
    with _robots_lock:
        cached = _robots_cache.get(host)
        if cached and now - cached[1] < ROBOTS_TTL:
            return cached[0]

    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(f"{host}/robots.txt")
    allowed = True
    try:
        resp = session().get(f"{host}/robots.txt", timeout=timeout)
        if resp.status_code == 200 and resp.text:
            rp.parse(resp.text.splitlines())
            allowed = rp.can_fetch(USER_AGENT, url)
        elif resp.status_code in (401, 403):
            allowed = False
        else:
            allowed = True          # 404/5xx -> keine Regeln bekannt
    except requests.RequestException:
        allowed = True              # nicht erreichbar -> nicht blockieren

    with _robots_lock:
        _robots_cache[host] = (allowed, now)
    return allowed


def _get(url: str, timeout: float = DEFAULT_TIMEOUT, **kw) -> requests.Response:
    """GET mit Retries, Backoff und ``Retry-After``-Respektierung."""
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = session().get(url, timeout=timeout, **kw)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = float(resp.headers.get("Retry-After") or 0)
                if attempt < MAX_RETRIES:
                    time.sleep(min(wait or (0.6 * (attempt + 1)), 5))
                    continue
            return resp
        except requests.RequestException as exc:      # Timeout, DNS, TLS …
            last_exc = exc
            if attempt < MAX_RETRIES:
                time.sleep(0.5 * (attempt + 1))
    if last_exc:
        raise last_exc
    raise requests.RequestException(f"unbekannter Fehler bei {url}")


# --------------------------------------------------------------------------
# Zeitstempel
# --------------------------------------------------------------------------
def _to_dt(value) -> datetime | None:
    """Macht aus allem, was feedparser/Reddit liefern, ein UTC-datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (tuple, list)) and len(value) >= 6:
        try:
            dt = datetime(*value[:6])
        except (TypeError, ValueError):
            return None
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(value, tz=timezone.utc)
    elif isinstance(value, str):
        txt = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(txt)
        except ValueError:
            for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                        "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(txt, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _clean(text: str, limit: int = 320) -> str:
    """HTML -> Klartext, gekürzt."""
    if not text:
        return ""
    txt = re.sub(r"<[^>]+>", " ", text)
    txt = html.unescape(txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    if len(txt) > limit:
        txt = txt[: limit - 1].rsplit(" ", 1)[0] + " …"
    return txt


def _url_slug(link: str) -> str:
    """Pfad einer URL in Kleinform (für die Veedel-Erkennung)."""
    return urlparse(link).path.lower().strip("/")


url_slug = _url_slug      # öffentlicher Alias


# --------------------------------------------------------------------------
# RSS / Atom
# --------------------------------------------------------------------------
def parse_feed(payload, source_name: str, base_url: str = "", kind: str = "news") -> list[Item]:
    """Parst RSS/Atom aus **Bytes/String** (nicht aus einer URL!).

    Dadurch greift unser eigener User-Agent – der Kern des Reddit-Fixes.
    """
    parsed = feedparser.parse(payload)
    if parsed.bozo and not parsed.entries and not parsed.feed:
        raise ValueError(f"kein gültiger Feed ({getattr(parsed, 'bozo_exception', 'unbekannt')})")

    fallback_title = parsed.feed.get("title") or source_name
    out: list[Item] = []
    for entry in parsed.entries:
        link = entry.get("link") or ""
        if not link:
            for alt in entry.get("links", []) or []:
                if alt.get("href"):
                    link = alt["href"]
                    break
        if not link:
            continue
        if base_url:
            link = urljoin(base_url, link)

        title = _clean(entry.get("title") or "Ohne Titel", 300)
        raw_summary = entry.get("summary") or entry.get("description") or ""
        if not raw_summary:
            content = entry.get("content") or []
            if content and isinstance(content, list):
                raw_summary = content[0].get("value", "") if isinstance(content[0], dict) else ""
        summary = _clean(raw_summary, 320)
        published = _to_dt(
            entry.get("published_parsed") or entry.get("updated_parsed")
            or entry.get("published") or entry.get("updated") or entry.get("date")
        )
        image = ""
        media = entry.get("media_thumbnail") or entry.get("media_content") or []
        if media and isinstance(media, list):
            image = media[0].get("url", "") if isinstance(media[0], dict) else ""
        if not image:
            enc = entry.get("enclosures") or []
            for e in enc:
                if "image" in (e.get("type", "") or ""):
                    image = e.get("href", "")
                    break
        if not image:
            m = re.search(r'<img[^>]+src="([^"]+)"', entry.get("summary", "") or "")
            if m:
                image = html.unescape(m.group(1))

        out.append(Item(
            title=title,
            link=link,
            source=source_name or fallback_title,
            published=published,
            teaser=summary,
            author=(entry.get("author") or "").strip(),
            image=image,
            kind=kind,
            url_slug=_url_slug(link),
        ))
    return out


def fetch_rss(name: str, url: str, kind: str = "news", group: str = "medien") -> SourceResult:
    """Holt einen RSS/Atom-Feed und liefert ein :class:`SourceResult`."""
    started = time.time()
    try:
        if not robots_ok(url):
            return SourceResult(
                name=name, url=url, ok=False, group=group,
                error="von robots.txt nicht freigegeben",
                hint="Die Quelle verbietet automatisierte Abrufe; sie wird übersprungen.",
                seconds=time.time() - started,
            )
        resp = _get(url)
        if resp.status_code != 200:
            return SourceResult(
                name=name, url=url, ok=False, group=group,
                error=f"HTTP {resp.status_code}",
                seconds=time.time() - started,
            )
        items = parse_feed(resp.content, name, url, kind=kind)
        if not items:
            return SourceResult(
                name=name, url=url, ok=True, items=[], group=group,
                error="Feed erreichbar, aber aktuell ohne Einträge",
                seconds=time.time() - started, used=url,
            )
        return SourceResult(
            name=name, url=url, ok=True, items=items, group=group,
            seconds=time.time() - started, used=url,
        )
    except Exception as exc:                            # noqa: BLE001
        return SourceResult(
            name=name, url=url, ok=False, group=group,
            error=f"{type(exc).__name__}: {exc}",
            seconds=time.time() - started,
        )


# --------------------------------------------------------------------------
# HTML (für Portale ohne Feed, z. B. koeln0221.de)
# --------------------------------------------------------------------------
def discover_feed_url(page_url: str) -> str | None:
    """Findet im HTML einer Seite einen ``<link rel="alternate" ...>``-Feed."""
    try:
        resp = _get(page_url, timeout=min(DEFAULT_TIMEOUT, 6))
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text[:400_000], "html.parser")
        for link in soup.find_all("link", rel=lambda r: r and "alternate" in r):
            typ = (link.get("type") or "").lower()
            href = link.get("href")
            if href and ("rss" in typ or "atom" in typ or "xml" in typ):
                return urljoin(page_url, href)
    except Exception:                                    # noqa: BLE001
        return None
    return None


def fetch_html(name: str, url: str, group: str = "medien") -> SourceResult:
    """Liest Überschriften aus einer HTML-Seite (Notlösung ohne RSS)."""
    started = time.time()
    try:
        if not robots_ok(url):
            return SourceResult(
                name=name, url=url, ok=False, group=group,
                error="von robots.txt nicht freigegeben", seconds=time.time() - started,
            )
        resp = _get(url)
        if resp.status_code != 200:
            return SourceResult(name=name, url=url, ok=False, group=group,
                                error=f"HTTP {resp.status_code}",
                                seconds=time.time() - started)
        soup = BeautifulSoup(resp.text, "html.parser")
        site_title = soup.title.get_text(strip=True) if soup.title else name
        items: list[Item] = []
        seen: set[str] = set()

        candidates: Iterable = soup.find_all("article") or []
        if not candidates:
            candidates = soup.find_all(["h2", "h3"])

        for node in candidates:
            a = node if node.name == "a" else node.find("a", href=True)
            if not a:
                continue
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 20:
                continue
            link = urljoin(url, a["href"])
            if link in seen:
                continue
            seen.add(link)

            published = None
            t = node.find("time") if node.name != "time" else node
            if t is not None:
                published = _to_dt(t.get("datetime") or t.get_text(strip=True))

            teaser_node = node.find(["p", "div"], class_=re.compile("teaser|summary|desc", re.I))
            teaser = _clean(teaser_node.get_text(" ", strip=True)) if teaser_node else ""

            img = node.find("img")
            image = urljoin(url, img.get("src", "")) if img and img.get("src") else ""

            items.append(Item(
                title=_clean(title, 300), link=link, source=name or site_title,
                published=published, teaser=teaser, image=image,
                url_slug=_url_slug(link),
            ))

        items = items[:40]
        return SourceResult(name=name, url=url, ok=True, items=items, group=group,
                            seconds=time.time() - started, used=url)
    except Exception as exc:                             # noqa: BLE001
        return SourceResult(name=name, url=url, ok=False, group=group,
                            error=f"{type(exc).__name__}: {exc}",
                            seconds=time.time() - started)


# --------------------------------------------------------------------------
# Reddit: Kaskade mit Diagnose
# --------------------------------------------------------------------------
def _reddit_token() -> str | None:
    """OAuth-Token für eine eigene Reddit-App (optional, via Umgebungsvariablen)."""
    if not (REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET):
        return None
    try:
        resp = session().post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
    except Exception:                                    # noqa: BLE001
        return None
    return None


def _reddit_endpoints(path: str) -> list[tuple[str, str]]:
    """Reihenfolge der Reddit-Endpunkte: (Label, URL)."""
    hosts = ["https://www.reddit.com", "https://old.reddit.com"]
    if REDDIT_MIRROR:
        hosts.insert(0, REDDIT_MIRROR.rstrip("/"))
    out: list[tuple[str, str]] = []
    for host in hosts:
        label = host.split("//")[-1]
        out.append((f"{label} .rss", f"{host}{path}.rss?limit=50&raw_json=1"))
        out.append((f"{label} .json", f"{host}{path}.json?limit=50&raw_json=1"))
    return out


def _items_from_reddit_json(data: dict, source: str) -> list[Item]:
    out: list[Item] = []
    for child in (data.get("data", {}).get("children") or []):
        d = child.get("data", {})
        title = d.get("title") or ""
        if not title:
            continue
        permalink = d.get("permalink") or ""
        link = f"https://www.reddit.com{permalink}" if permalink else d.get("url", "")
        teaser = _clean(d.get("selftext") or "", 320)
        if not teaser and d.get("url_overridden_by_dest") and not d.get("is_self"):
            teaser = f"Link: {d['url_overridden_by_dest']}"
        out.append(Item(
            title=_clean(title, 300),
            link=link,
            source=source,
            published=_to_dt(d.get("created_utc")),
            teaser=teaser,
            author=d.get("author") or "",
            image=(d.get("preview", {}).get("images", [{}])[0].get("source", {}).get("url", "")
                   if d.get("preview") else ""),
            kind="forum",
            url_slug=_url_slug(link),
        ))
    return out


def fetch_reddit(name: str, path: str, group: str = "foren") -> SourceResult:
    """Holt einen Subreddit-Feed – mit Kaskade, OAuth-Fallback und Diagnose.

    ``path`` ist z. B. ``/r/Koeln/new``. Die globale Reddit-Suche
    (``/search``) wird bewusst **nicht** verwendet: Die ist laut robots.txt
    gesperrt. Stattdessen holen wir die Subreddits und filtern lokal nach
    Veedel – das ist genauer und braucht weniger Requests.
    """
    started = time.time()
    errors: list[str] = []

    if not robots_ok(f"https://www.reddit.com{path}"):
        return SourceResult(
            name=name, url=f"https://www.reddit.com{path}", ok=False, group=group,
            error="reddit.com/robots.txt verbietet diesen Pfad",
            hint="Reddit erlaubt den Abruf nicht – Quelle übersprungen.",
            seconds=time.time() - started,
        )

    # 1) OAuth, falls eigene App-Daten gesetzt sind (der zuverlässigste Weg)
    token = _reddit_token()
    if token:
        try:
            resp = session().get(
                f"https://oauth.reddit.com{path}",
                params={"limit": 50, "raw_json": 1},
                headers={"Authorization": f"Bearer {token}"},
                timeout=DEFAULT_TIMEOUT,
            )
            if resp.status_code == 200:
                items = _items_from_reddit_json(resp.json(), name)
                if items:
                    return SourceResult(name=name, url=f"oauth.reddit.com{path}", ok=True,
                                        items=items, group=group, used="OAuth (eigene App)",
                                        seconds=time.time() - started)
                errors.append("oauth: 200, aber keine Beiträge")
            else:
                errors.append(f"oauth: HTTP {resp.status_code}")
        except Exception as exc:                         # noqa: BLE001
            errors.append(f"oauth: {type(exc).__name__}")

    # 2) öffentliche Endpunkte durchprobieren
    for label, url in _reddit_endpoints(path):
        try:
            resp = _get(url, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException as exc:
            errors.append(f"{label}: {type(exc).__name__}")
            continue

        if resp.status_code in (403, 429, 451):
            errors.append(f"{label}: HTTP {resp.status_code} (Reddit blockt diese IP/den Abruf)")
            continue
        if resp.status_code != 200:
            errors.append(f"{label}: HTTP {resp.status_code}")
            continue

        ctype = (resp.headers.get("Content-Type") or "").lower()
        try:
            if "json" in ctype or resp.text.lstrip().startswith("{"):
                items = _items_from_reddit_json(resp.json(), name)
            else:
                items = parse_feed(resp.content, name, url, kind="forum")
        except Exception as exc:                         # noqa: BLE001
            errors.append(f"{label}: Parsefehler {type(exc).__name__}")
            continue

        if items:
            return SourceResult(name=name, url=url, ok=True, items=items,
                                group=group, used=label, seconds=time.time() - started)
        errors.append(f"{label}: 200, aber keine Beiträge")

    # 3) alle Wege fehlgeschlagen -> ehrliche Diagnose + Tipp
    hint = (
        "Reddit blockt Server-IPs ohne Login. Abhilfe: unter "
        "https://www.reddit.com/prefs/apps eine kostenlose Script-App anlegen und "
        "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET setzen. Die restlichen Quellen "
        "funktionieren unabhängig davon."
    )
    return SourceResult(
        name=name, url=f"https://www.reddit.com{path}", ok=False, group=group,
        error="; ".join(errors) or "keine Antwort",
        hint=hint, seconds=time.time() - started,
    )


# --------------------------------------------------------------------------
# Kleine Hilfen
# --------------------------------------------------------------------------
def fingerprint(item: Item) -> str:
    """Stabiler Fingerabdruck für Dedup + Cache."""
    base = f"{item.title.lower()}|{item.link.lower()}"
    return hashlib.sha1(base.encode("utf-8", "ignore")).hexdigest()[:16]


def items_to_json(items: list[Item]) -> str:
    return json.dumps([i.to_dict() for i in items], ensure_ascii=False)
