# -*- coding: utf-8 -*-
"""Local News Aggregator – crawler‑based MVP.

- Enter a city / quarter → automatic discovery of local news sources
  (web‑search‑derived RSS / HTML pages) and display a stream + summary.
- Weather (optional, needs OWM_API_KEY).
- No manual URL handling required – the crawler finds sensible sources
  for the entered location.

Run with:  python app.py
Then open http://127.0.0.1:5000  (bind to 0.0.0.0 for the preview).
"""

import os
from collections import defaultdict
from datetime import datetime, timedelta
from flask import Flask, render_template, request, abort

import feedparser
import requests

app = Flask(__name__)

# ---------------------------------------------------------
# 1️⃣  IMPORT CRAWLER (automatic source discovery)
# ---------------------------------------------------------
from crawler import crawl_for_city

# ---------------------------------------------------------
# 2️⃣  CONFIGURATION
# ---------------------------------------------------------

# ---- OpenWeatherMap (optional) ----
# Get a free key at https://openweathermap.org/api  and set the env var:
OWM_API_KEY = os.getenv("OWM_API_KEY", "")

# ---------------------------------------------------------
# 3️⃣  HELPERS
# ---------------------------------------------------------

def get_weather(city="Berlin"):
    """Fetch current weather for *city* via OpenWeatherMap.

    Requires OWM_API_KEY in the environment. Returns a dict or None.
    """
    if not OWM_API_KEY:
        return None
    try:
        resp = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": city, "appid": OWM_API_KEY, "units": "metric", "lang": "de"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return {
            "city": city,
            "temp": round(data["main"]["temp"]),
            "desc": data["weather"][0]["description"].capitalize(),
            "icon": data["weather"][0]["icon"],
        }
    except Exception as exc:
        print(f"Weather fetch error: {exc}")
        return None


# ---------------------------------------------------------
# 4️⃣  FLASK ROUTES
# ---------------------------------------------------------

@app.route("/", methods=["GET", "POST"])
def index():
    summary = None
    stream = None
    weather = None
    city = ""

    if request.method == "POST":
        city = request.form.get("city", "").strip() or "Köln‑Deutz"
        # ---- automatic crawl of discovered local sources ----
        data = crawl_for_city(city, max_items=30)
        stream = data["stream"]
        summary = data["summary"]
        # weather (optional)
        weather = get_weather(city)

    return render_template(
        "index.html",
        city=city,
        summary=summary,
        stream=stream,
        weather=weather,
    )


# ---------------------------------------------------------
# 5️⃣  MAIN
# ---------------------------------------------------------

if __name__ == "__main__":
    # bind to 0.0.0.0 so the Arena preview can reach it
    app.run(host="0.0.0.0", port=5000, debug=False)
