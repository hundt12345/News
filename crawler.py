# crawler.py – automatic local‑news discovery for a given city/quarter
# ---------------------------------------------------------------
# Provides:
#   crawl_for_city(city: str, max_items: int = 30) -> dict
#       returns {"stream": [...], "summary": {...}}
# ---------------------------------------------------------------

import time
import urllib.robotparser
from collections import defaultdict
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
import feedparser

# --------------------------------------------------------------
# 1. SOURCE CONFIGURATION
# --------------------------------------------------------------
# Each entry: (base_url, rss_url)
#   - if rss_url is given, the crawler will use feedparser to fetch entries.
#   - if rss_url is None, the crawler will parse the base_url HTML.
# Sources were discovered automatically (web search) for "Köln Deutz".
SOURCES = {
    # Known local newspaper (already covered)
    "Kölner Stadt‑Anzeiger (Deutz)": (
        "https://www.ksta.de/koeln/koelner-innenstadt/deutz",
        None,
    ),
    # Popular news portal
    "Deutz bei t‑Online": (
        "https://koeln.t-online.de/region/koeln/id_101469632/deutz",
        None,
    ),
    # Community‑site with events & news
    "koelner.de": (
        "https://www.koelner.de",
        None,
    ),
    # Official city press‑release RSS feed (covers whole city, includes district news)
    "Stadt Köln Pressemeldungen": (
        None,
        "https://www.stadt-koeln.de/externe-dienste/rss/pressemeldungen.xml",
    ),
    # Reddit sources - city-specific subreddits and search
    "Reddit r/Koeln": (
        None,
        "https://www.reddit.com/r/koeln/.rss",
    ),
    "Reddit r/de": (
        None,
        "https://www.reddit.com/r/de/.rss",
    ),
    "Reddit r/worldnews": (
        None,
        "https://www.reddit.com/r/worldnews/.rss",
    ),
}

# --------------------------------------------------------------
# 2. Helper: robots.txt check
# --------------------------------------------------------------
def _robots_ok(url: str) -> bool:
    """Return True if robots.txt permits fetching *url*."""
    parsed = requests.utils.urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch("*", url)
    except Exception:
        return True  # be permissive on error


# --------------------------------------------------------------
# 3. Fetch & parse HTML start page – extract article headlines
# --------------------------------------------------------------
def _fetch_beauty(url: str) -> BeautifulSoup:
    """Download a page, respect a short politeness pause, return BeautifulSoup."""
    time.sleep(1)  # courteous delay
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def _extract_items_from_soup(soup: BeautifulSoup, base: str) -> list[dict]:
    """Heuristic: take every <h2> or <h3> that contains an <a>."""
    items = []
    for h in soup.find_all(["h2", "h3"]):
        a = h.find("a", href=True)
        if not a:
            continue
        title = a.get_text(strip=True)
        link = a["href"]
        link = urljoin(base, link)  # make absolute
        # try to find a <time> element somewhere nearby
        date = None
        time_tag = h.find_next("time")
        if time_tag and time_tag.get("datetime"):
            try:
                date = datetime.fromisoformat(time_tag["datetime"])
            except ValueError:
                pass
        items.append(
            {
                "title": title,
                "link": link,
                "source": soup.title.string if hasattr(soup, "title") else "Unknown",
                "published": date,
            }
        )
    return items


# --------------------------------------------------------------
# 4. RSS‑feed extraction
# --------------------------------------------------------------
def _extract_items_from_rss(feed_url: str) -> list[dict]:
    """Parse an RSS/Atom feed and return a list of dicts."""
    f = feedparser.parse(feed_url)
    out = []
    for entry in f.entries:
        out.append(
            {
                "title": entry.get("title", "Ohne Titel"),
                "link": entry.link,
                "source": f.feed.get("title", "RSS"),
                "published": (
                    datetime(*entry.published_parsed[:6]) if entry.published_parsed else None
                ),
            }
        )
    return out


# --------------------------------------------------------------
# 5. Main crawl function
# --------------------------------------------------------------
def crawl_for_city(city: str, max_items: int = 30) -> dict:
    """
    Crawl all sources listed in SOURCES that are relevant to *city*.
    The function is city‑aware only by using the city name in the returned
    metadata; the actual source list is static (pre‑discovered).
    Additionally adds dynamic Reddit sources based on the city name.

    Returns a dict with:
        - "stream": list of the newest max_items articles (sorted by date)
        - "summary": dict grouping those articles by the first word of the title
    """
    all_entries = []

    # Build dynamic sources list - start with static SOURCES
    sources_to_crawl = dict(SOURCES)
    
    # Add city-specific Reddit RSS feeds
    city_lower = city.lower().strip()
    city_subreddit = city_lower.replace(" ", "").replace("-", "").replace(".", "")
    
    # Add city subreddit if it exists
    if city_subreddit:
        sources_to_crawl[f"Reddit r/{city_subreddit}"] = (
            None,
            f"https://www.reddit.com/r/{city_subreddit}/.rss",
        )
    
    # Add German city subreddits for common cities
    german_cities = ["berlin", "hamburg", "munich", "muenchen", "cologne", "koeln", 
                     "frankfurt", "stuttgart", "dusseldorf", "duesseldorf", "leipzig",
                     "dresden", "nuremberg", "nuernberg", "hannover", "bremen"]
    if city_lower in german_cities:
        sources_to_crawl[f"Reddit r/{city_lower}"] = (
            None,
            f"https://www.reddit.com/r/{city_lower}/.rss",
        )
    
    # Also add search for the city on Reddit
    sources_to_crawl[f"Reddit Search: {city}"] = (
        None,
        f"https://www.reddit.com/search.rss?q={city}",
    )

    for source_name, (base_url, rss_url) in sources_to_crawl.items():
        # ---- If an RSS URL is given, use it directly ---------------------------------
        if rss_url:
            if not _robots_ok(rss_url):
                continue
            try:
                all_entries.extend(_extract_items_from_rss(rss_url))
            except Exception as exc:
                print(f"RSS-Fehler bei {source_name}: {exc}")
            continue

        # ---- Otherwise crawl the start page -----------------------------------------
        if not base_url:
            continue
        if not _robots_ok(base_url):
            continue
        try:
            soup = _fetch_beauty(base_url)
            soup.base_url = base_url  # make urljoin work inside the function
            all_entries.extend(_extract_items_from_soup(soup, base_url))
        except Exception as exc:
            print(f"HTML‑Crawl-Fehler bei {source_name}: {exc}")

        # polite pause between different hosts
        time.sleep(1)

    # --------------------------------------------------------------
    # 6. Clean & sort
    # --------------------------------------------------------------
    # Keep only entries with a title
    all_entries = [e for e in all_entries if e["title"]]

    # Sort newest first (missing dates go to the end)
    all_entries.sort(
        key=lambda e: e["published"] or datetime.min,
        reverse=True,
    )

    # Limit to max_items
    stream = all_entries[:max_items]

    # --------------------------------------------------------------
    # 7. Simple summary – group by first word of the title
    # --------------------------------------------------------------
    groups = defaultdict(list)
    for item in stream:
        key = item["title"].split()[0].lower() if item["title"].split() else "other"
        groups[key].append(item)
    summary = {k: v[:3] for k, v in groups.items()}  # up to 3 per group

    return {"stream": stream, "summary": summary}
