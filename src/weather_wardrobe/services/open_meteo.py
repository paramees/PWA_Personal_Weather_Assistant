from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from weather_wardrobe.models import HourlyWeatherPoint, LocationCandidate

WMO_CODES: dict[int, tuple[str, str]] = {
    0: ("☀️", "Ясно"),
    1: ("🌤", "Преимущественно ясно"),
    2: ("⛅", "Переменная облачность"),
    3: ("☁️", "Пасмурно"),
    45: ("🌫", "Туман"),
    48: ("🌫", "Изморозь"),
    51: ("🌦", "Слабая морось"),
    53: ("🌦", "Морось"),
    55: ("🌧", "Сильная морось"),
    56: ("🌧", "Ледяная морось"),
    57: ("🌧", "Сильная ледяная морось"),
    61: ("🌦", "Небольшой дождь"),
    63: ("🌧", "Дождь"),
    65: ("🌧", "Сильный дождь"),
    66: ("🌨", "Ледяной дождь"),
    67: ("🌨", "Сильный ледяной дождь"),
    71: ("🌨", "Небольшой снег"),
    73: ("❄️", "Снег"),
    75: ("❄️", "Сильный снег"),
    77: ("🌨", "Снежная крупа"),
    80: ("🌦", "Небольшой ливень"),
    81: ("🌧", "Ливень"),
    82: ("⛈", "Сильный ливень"),
    85: ("🌨", "Снегопад"),
    86: ("❄️", "Сильный снегопад"),
    95: ("⛈", "Гроза"),
    96: ("⛈", "Гроза с градом"),
    99: ("⛈", "Сильная гроза с градом"),
}


def describe_wmo_code(code: int) -> tuple[str, str]:
    """Map WMO weather interpretation code to (emoji, Russian description)."""
    return WMO_CODES.get(code, ("🌡", "Переменная погода"))


def _get_val(seq: list[Any], idx: int, default: float | int) -> float | int:
    if idx >= len(seq) or seq[idx] is None:
        return default
    return seq[idx]


class OpenMeteoClient:
    """Async client for Open-Meteo geocoding, weather forecast, and reverse geocoding."""

    GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
    NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
    NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"

    HOURLY_FIELDS = ",".join(
        [
            "temperature_2m",
            "apparent_temperature",
            "relative_humidity_2m",
            "precipitation_probability",
            "precipitation",
            "rain",
            "snowfall",
            "weather_code",
            "wind_speed_10m",
            "wind_gusts_10m",
            "uv_index",
        ]
    )

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self.http = http_client

    async def search_cities(self, query: str, count: int = 5) -> list[LocationCandidate]:
        """Search cities by name via Open-Meteo Geocoding API."""
        cleaned = query.strip()
        if not cleaned:
            return []
        resp = await self.http.get(
            self.GEOCODING_URL,
            params={
                "name": cleaned,
                "count": count,
                "language": "ru",
                "format": "json",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results") or []
        candidates: list[LocationCandidate] = []
        for item in results:
            candidates.append(
                LocationCandidate(
                    name=item["name"],
                    country=item.get("country") or "",
                    admin1=item.get("admin1"),
                    latitude=float(item["latitude"]),
                    longitude=float(item["longitude"]),
                    timezone=item.get("timezone") or "UTC",
                )
            )
        return candidates

    async def search_places(self, query: str, count: int = 5) -> list[LocationCandidate]:
        """Search cities via Open-Meteo, falling back to Nominatim for districts/addresses."""
        cleaned = query.strip()
        if not cleaned:
            return []
        cities = await self.search_cities(cleaned, count=count)
        if cities:
            return cities

        try:
            resp = await self.http.get(
                self.NOMINATIM_SEARCH_URL,
                params={
                    "q": cleaned,
                    "format": "json",
                    "limit": count,
                    "accept-language": "ru",
                    "addressdetails": 1,
                },
                headers={"User-Agent": "WeatherWardrobeBot/1.0"},
                timeout=4.0,
            )
            resp.raise_for_status()
            items = resp.json()
        except Exception:
            return []

        candidates: list[LocationCandidate] = []
        for item in items:
            address = item.get("address") or {}
            short_name = (
                item.get("name")
                or address.get("suburb")
                or address.get("city_district")
                or address.get("city")
                or cleaned
            )
            city_or_region = (
                address.get("city")
                or address.get("town")
                or address.get("state")
                or address.get("county")
            )
            country = address.get("country") or ""
            candidates.append(
                LocationCandidate(
                    name=str(short_name),
                    admin1=str(city_or_region) if city_or_region else None,
                    country=str(country),
                    latitude=float(item["lat"]),
                    longitude=float(item["lon"]),
                    timezone="",
                )
            )
        return candidates

    async def reverse_geocode_city(self, lat: float, lon: float) -> str:
        """Best-effort human-readable city name for Telegram GPS coordinates."""
        fallback = f"{lat:.2f}, {lon:.2f}"
        try:
            resp = await self.http.get(
                self.NOMINATIM_REVERSE_URL,
                params={
                    "lat": lat,
                    "lon": lon,
                    "format": "json",
                    "accept-language": "ru",
                },
                headers={"User-Agent": "WeatherWardrobeBot/1.0"},
                timeout=3.0,
            )
            resp.raise_for_status()
            data = resp.json()
            address = data.get("address") or {}
            place = (
                address.get("city")
                or address.get("town")
                or address.get("village")
                or address.get("municipality")
                or address.get("county")
            )
            country = address.get("country")
            if place and country:
                return f"{place}, {country}"
            if place:
                return str(place)
        except Exception:
            return fallback
        return fallback

    async def fetch_forecast(
        self,
        lat: float,
        lon: float,
        days: int = 2,
    ) -> tuple[str, list[HourlyWeatherPoint]]:
        """Fetch hourly forecast and return (IANA timezone, HourlyWeatherPoint list)."""
        resp = await self.http.get(
            self.FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": self.HOURLY_FIELDS,
                "wind_speed_unit": "ms",
                "timezone": "auto",
                "forecast_days": days,
            },
            timeout=12.0,
        )
        resp.raise_for_status()
        data = resp.json()
        tz_name = data.get("timezone") or "UTC"
        hourly = data.get("hourly") or {}
        times = hourly.get("time") or []

        temps = hourly.get("temperature_2m") or []
        apparents = hourly.get("apparent_temperature") or []
        humidities = hourly.get("relative_humidity_2m") or []
        precip_probs = hourly.get("precipitation_probability") or []
        precips = hourly.get("precipitation") or []
        rains = hourly.get("rain") or []
        snows = hourly.get("snowfall") or []
        codes = hourly.get("weather_code") or []
        winds = hourly.get("wind_speed_10m") or []
        gusts = hourly.get("wind_gusts_10m") or []
        uvs = hourly.get("uv_index") or []

        points: list[HourlyWeatherPoint] = []
        for idx, ts in enumerate(times):
            points.append(
                HourlyWeatherPoint(
                    time=datetime.fromisoformat(ts),
                    temp=float(_get_val(temps, idx, 0.0)),
                    apparent_temp=float(_get_val(apparents, idx, _get_val(temps, idx, 0.0))),
                    humidity=int(_get_val(humidities, idx, 0)),
                    precip_prob=int(_get_val(precip_probs, idx, 0)),
                    precipitation_mm=float(_get_val(precips, idx, 0.0)),
                    rain_mm=float(_get_val(rains, idx, 0.0)),
                    snowfall_cm=float(_get_val(snows, idx, 0.0)),
                    weather_code=int(_get_val(codes, idx, 0)),
                    wind_speed_ms=float(_get_val(winds, idx, 0.0)),
                    wind_gusts_ms=float(_get_val(gusts, idx, 0.0)),
                    uv_index=float(_get_val(uvs, idx, 0.0)),
                )
            )
        return tz_name, points
