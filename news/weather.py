# -*- coding: utf-8 -*-
"""Wetter für den Ort – optional, aber jetzt **ohne API-Key nutzbar**.

Reihenfolge:
1. OpenWeatherMap, falls ``OWM_API_KEY`` gesetzt ist (wie bisher).
2. Open-Meteo (kostenlos, kein Key, keine Registrierung) als Standard.

Fehlt beides oder ist das Netz weg, liefert die Funktion ``None`` und die
Oberfläche blendet das Wetter einfach aus.
"""

from __future__ import annotations

import os

from .fetch import DEFAULT_TIMEOUT, session

OWM_API_KEY = os.environ.get("OWM_API_KEY", "")

# WMO-Wettercodes von Open-Meteo -> (Text, Symbol)
WMO = {
    0: ("Klar", "☀️"), 1: ("Überwiegend klar", "🌤️"), 2: ("Teilweise bewölkt", "⛅"),
    3: ("Bedeckt", "☁️"), 45: ("Nebel", "🌫️"), 48: ("Reifnebel", "🌫️"),
    51: ("Leichter Nieselregen", "🌦️"), 53: ("Nieselregen", "🌦️"),
    55: ("Starker Nieselregen", "🌧️"), 56: ("Gefrierender Nieselregen", "🌧️"),
    57: ("Gefrierender Nieselregen", "🌧️"), 61: ("Leichter Regen", "🌦️"),
    63: ("Regen", "🌧️"), 65: ("Starker Regen", "🌧️"),
    66: ("Gefrierender Regen", "🌧️"), 67: ("Gefrierender Regen", "🌧️"),
    71: ("Leichter Schneefall", "🌨️"), 73: ("Schneefall", "❄️"),
    75: ("Starker Schneefall", "❄️"), 77: ("Schneegriesel", "🌨️"),
    80: ("Leichte Schauer", "🌦️"), 81: ("Schauer", "🌧️"),
    82: ("Kräftige Schauer", "⛈️"), 85: ("Schneeschauer", "🌨️"),
    86: ("Schneeschauer", "🌨️"), 95: ("Gewitter", "⛈️"),
    96: ("Gewitter mit Hagel", "⛈️"), 99: ("Gewitter mit Hagel", "⛈️"),
}

# Grobe Koordinaten, damit die Geocoding-Anfrage eingespart werden kann
BEKANNTE_ORTE = {
    "köln": (50.9375, 6.9603), "cologne": (50.9375, 6.9603),
    "bonn": (50.7374, 7.0982), "leverkusen": (51.0459, 7.0182),
}


def _owm(city: str) -> dict | None:
    if not OWM_API_KEY:
        return None
    try:
        resp = session().get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": city, "appid": OWM_API_KEY, "units": "metric", "lang": "de"},
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        d = resp.json()
        return {
            "ort": d.get("name", city),
            "temp": round(d["main"]["temp"]),
            "text": d["weather"][0]["description"].capitalize(),
            "icon": "🌡️",
            "min": round(d["main"]["temp_min"]),
            "max": round(d["main"]["temp_max"]),
            "wind": round(d["wind"].get("speed", 0)),
            "quelle": "OpenWeatherMap",
        }
    except Exception:                                      # noqa: BLE001
        return None


def _geocode(city: str) -> tuple[float, float] | None:
    key = city.strip().lower().replace("köln", "köln")
    if key in BEKANNTE_ORTE:
        return BEKANNTE_ORTE[key]
    try:
        resp = session().get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "de", "format": "json"},
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        hits = resp.json().get("results") or []
        if hits:
            return hits[0]["latitude"], hits[0]["longitude"]
    except Exception:                                      # noqa: BLE001
        return None
    return None


def _open_meteo(city: str) -> dict | None:
    coords = _geocode(city)
    if not coords:
        return None
    lat, lon = coords
    try:
        resp = session().get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat, "longitude": lon,
                "current": "temperature_2m,weather_code,wind_speed_10m,apparent_temperature",
                "daily": "temperature_2m_max,temperature_2m_min",
                "timezone": "Europe/Berlin", "forecast_days": 1,
            },
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        d = resp.json()
        cur = d.get("current") or d.get("current_weather") or {}
        code = int(cur.get("weather_code", -1))
        text, icon = WMO.get(code, ("—", "🌡️"))
        daily = d.get("daily") or {}
        return {
            "ort": city,
            "temp": round(float(cur.get("temperature_2m", cur.get("temperature", 0)))),
            "text": text,
            "icon": icon,
            "min": round(float(daily["temperature_2m_min"][0])) if daily.get("temperature_2m_min") else None,
            "max": round(float(daily["temperature_2m_max"][0])) if daily.get("temperature_2m_max") else None,
            "wind": round(float(cur.get("wind_speed_10m", 0))),
            "quelle": "Open-Meteo",
        }
    except Exception:                                      # noqa: BLE001
        return None


def get_weather(city: str = "Köln") -> dict | None:
    """Aktuelles Wetter – erst OWM (mit Key), dann Open-Meteo (ohne Key)."""
    return _owm(city) or _open_meteo(city)
