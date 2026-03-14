"""Weather API — proxies Open-Meteo (free, no API key) with caching."""

import time
from urllib.parse import quote

import httpx
from fastapi import APIRouter

from app_config import get_profile

router = APIRouter(prefix="/api/weather", tags=["weather"])

# In-memory cache: { "weather": {...}, "coords": (lat, lon), "ts": float }
_cache: dict = {}
CACHE_TTL = 30 * 60  # 30 minutes

# WMO weather code → human-readable condition
_WMO_CONDITIONS = {
    0: "clear",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "freezing fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    56: "freezing drizzle",
    57: "heavy freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "heavy freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light showers",
    81: "showers",
    82: "heavy showers",
    85: "light snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "severe thunderstorm",
}


def _geocode_location(location: str) -> tuple[float, float, str] | None:
    """Geocode a location string to (lat, lon, display_name) via Open-Meteo."""
    try:
        resp = httpx.get(
            f"https://geocoding-api.open-meteo.com/v1/search?name={quote(location)}&count=1",
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if results:
            r = results[0]
            name = r.get("name", location)
            admin = r.get("admin1", "")
            display = f"{name}, {admin}" if admin else name
            return r["latitude"], r["longitude"], display
    except Exception:
        pass
    return None


def _detect_location_by_ip() -> tuple[float, float, str] | None:
    """Auto-detect location via IP geolocation."""
    try:
        resp = httpx.get("http://ip-api.com/json/?fields=lat,lon,city,regionName", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        city = data.get("city", "")
        region = data.get("regionName", "")
        display = f"{city}, {region}" if region else city
        return data["lat"], data["lon"], display
    except Exception:
        pass
    return None


def _get_coords() -> tuple[float, float, str] | None:
    """Get coordinates — from profile location or IP detection. Cached."""
    cached = _cache.get("coords")
    if cached and (time.time() - cached["ts"]) < CACHE_TTL:
        return cached["lat"], cached["lon"], cached["name"]

    profile = get_profile()
    location = profile.get("user_location", "").strip()

    result = None
    if location:
        result = _geocode_location(location)

    if not result:
        result = _detect_location_by_ip()

    if result:
        lat, lon, name = result
        _cache["coords"] = {"lat": lat, "lon": lon, "name": name, "ts": time.time()}
        return lat, lon, name

    return None


def get_weather() -> dict | None:
    """Fetch current weather. Returns dict or None. Cached for 30 min."""
    import os

    if os.environ.get("DEMO_MODE", "").strip() in ("1", "true", "yes"):
        return {"temp_f": 62, "condition": "partly cloudy", "location": "San Francisco, California"}

    cached = _cache.get("weather")
    if cached and (time.time() - cached["ts"]) < CACHE_TTL:
        return cached["data"]

    coords = _get_coords()
    if not coords:
        return None

    lat, lon, location_name = coords

    try:
        resp = httpx.get(
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,weather_code"
            f"&temperature_unit=fahrenheit",
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        current = data.get("current", {})
        temp_f = current.get("temperature_2m")
        code = current.get("weather_code", 0)
        condition = _WMO_CONDITIONS.get(code, "unknown")

        result = {
            "temp_f": round(temp_f) if temp_f is not None else None,
            "condition": condition,
            "location": location_name,
        }
        _cache["weather"] = {"data": result, "ts": time.time()}
        return result
    except Exception:
        return None


@router.get("")
def weather_endpoint():
    """Return current weather data."""
    data = get_weather()
    if data is None:
        return {"weather": None}
    return {"weather": data}
