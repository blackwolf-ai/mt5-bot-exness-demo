"""Free, keyless web APIs: weather (Open-Meteo) and FX rates (Frankfurter / ECB)."""
from __future__ import annotations

import httpx

WEATHER_CODES = {
    0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain",
    65: "heavy rain", 71: "light snow", 73: "snow", 75: "heavy snow", 80: "showers",
    81: "showers", 82: "violent showers", 95: "thunderstorm", 96: "thunderstorm + hail", 99: "thunderstorm + hail",
}


async def weather(city: str) -> str:
    async with httpx.AsyncClient(timeout=15) as client:
        geo = await client.get("https://geocoding-api.open-meteo.com/v1/search",
                               params={"name": city, "count": 1})
        geo.raise_for_status()
        results = geo.json().get("results") or []
        if not results:
            return f"City '{city}' not found."
        place = results[0]
        fc = await client.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": place["latitude"], "longitude": place["longitude"],
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto", "forecast_days": 1,
        })
        fc.raise_for_status()
        data = fc.json()
    cur, day = data["current"], data["daily"]
    return (
        f"{place['name']}, {place.get('country', '')}\n"
        f"{WEATHER_CODES.get(cur['weather_code'], 'n/a')}, {cur['temperature_2m']}°C "
        f"(feels {cur['apparent_temperature']}°C)\n"
        f"Humidity {cur['relative_humidity_2m']}%, wind {cur['wind_speed_10m']} km/h\n"
        f"Today {day['temperature_2m_min'][0]}–{day['temperature_2m_max'][0]}°C, "
        f"rain chance {day['precipitation_probability_max'][0]}%"
    )


async def fx_convert(amount: float, base: str, quote: str) -> str:
    base, quote = base.upper(), quote.upper()
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get("https://api.frankfurter.app/latest", params={"from": base, "to": quote})
        if r.status_code == 404:
            return "Unknown currency code."
        r.raise_for_status()
        data = r.json()
    rate = data["rates"][quote]
    return f"{amount:,.2f} {base} = {amount * rate:,.4f} {quote}\n(rate {rate}, ECB {data['date']})"


async def fetch_text(url: str, max_chars: int = 60000) -> str:
    """Fetch a page and strip it down to rough plain text for summarising."""
    import re
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 (TelegramBot)"}) as client:
        r = await client.get(url)
        r.raise_for_status()
        html = r.text
    html = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    if len(text) > max_chars:
        return text[:max_chars] + " [page truncated]"
    return text
