"""Live weather from the US National Weather Service (api.weather.gov — free, no key)."""
import re
from datetime import datetime

from .live import FeedError, get_json

POINTS = "https://api.weather.gov/points/{lat:.4f},{lon:.4f}"


def classify(short_forecast, precip_pct):
    """Map NWS text + precip probability onto the planner's weather buckets."""
    text = (short_forecast or "").lower()
    if (precip_pct or 0) >= 50 or re.search(r"rain|showers|drizzle|thunder", text):
        return "rain"
    if "fog" in text or "haze" in text:
        return "fog"
    return "clear"


def wind_mph(text):
    nums = [int(n) for n in re.findall(r"\d+", text or "")]
    return max(nums) if nums else 0


def pick_period(periods, hour):
    """The hourly period starting at `hour` today (or the first period if none matches)."""
    for p in periods:
        if datetime.fromisoformat(p["startTime"]).hour == hour:
            return p
    return periods[0]


def at(lat, lon, hour):
    """Forecast for `hour` (0–23) near lat/lon. Raises FeedError when NWS is unavailable."""
    point, _ = get_json(POINTS.format(lat=lat, lon=lon), ttl=86400, disk_ttl=86400)
    url = point["properties"]["forecastHourly"]
    hourly, meta = get_json(url, ttl=600)
    periods = hourly["properties"]["periods"]
    if not periods:
        raise FeedError("NWS returned no hourly periods")
    p = pick_period(periods, hour)
    precip = (p.get("probabilityOfPrecipitation") or {}).get("value") or 0
    return {
        "condition": classify(p.get("shortForecast"), precip),
        "summary": p.get("shortForecast", ""),
        "temp_f": p.get("temperature"),
        "wind_mph": wind_mph(p.get("windSpeed")),
        "precip_pct": precip,
        "is_daytime": p.get("isDaytime", True),
        "source": "NWS api.weather.gov",
        "cache": meta["cache"],
    }
