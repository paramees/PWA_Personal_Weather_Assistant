from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class DaySchedule(BaseModel):
    """Notification settings for a single weekday (0=Monday .. 6=Sunday)."""

    weekday: int = Field(ge=0, le=6)
    enabled: bool = False
    send_time: str = "08:00"


class UserProfile(BaseModel):
    """Stored user preferences, location, and personal wardrobe description."""

    user_id: int
    city_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    timezone: str = "UTC"
    active_start_hour: int = Field(default=8, ge=0, le=23)
    active_end_hour: int = Field(default=21, ge=0, le=23)
    comfort_offset: int = Field(default=0, ge=-5, le=5)
    wardrobe_text: str = ""
    use_ai: bool = True

    @property
    def has_location(self) -> bool:
        return self.latitude is not None and self.longitude is not None


class LocationCandidate(BaseModel):
    """Geocoding candidate returned by Open-Meteo geocoding API."""

    name: str
    country: str = ""
    admin1: str | None = None
    latitude: float
    longitude: float
    timezone: str = "UTC"

    @property
    def display_name(self) -> str:
        parts: list[str] = [self.name]
        for extra in (self.admin1, self.country):
            if extra and extra not in parts:
                parts.append(extra)
        return ", ".join(parts)


class HourlyWeatherPoint(BaseModel):
    """Single hourly meteorological observation/forecast point."""

    time: datetime
    temp: float
    apparent_temp: float
    humidity: int
    precip_prob: int
    precipitation_mm: float
    rain_mm: float
    snowfall_cm: float
    weather_code: int
    wind_speed_ms: float
    wind_gusts_ms: float
    uv_index: float


class SlotSummary(BaseModel):
    """Representative forecast snapshot for morning, day, or evening."""

    label: str
    hour: int
    temp: float
    apparent_temp: float
    weather_code: int
    condition_text: str
    condition_emoji: str
    wind_speed_ms: float
    precip_prob: int


class WeatherAlerts(BaseModel):
    """Deterministic safety and comfort flags derived from hourly weather data."""

    umbrella_required: bool = False
    rain_window: str | None = None
    snow_or_ice_risk: bool = False
    strong_wind: bool = False
    big_temp_swing: bool = False
    temp_swing_delta: float = 0.0
    high_uv: bool = False
    freezing_risk: bool = False
    heat_risk: bool = False


class DayWeatherSummary(BaseModel):
    """Aggregated meteorological summary for the user's active hours on target_date."""

    city_name: str
    target_date: date
    timezone: str
    active_start_hour: int
    active_end_hour: int
    morning: SlotSummary
    day: SlotSummary
    evening: SlotSummary
    temp_min: float
    temp_max: float
    feels_min: float
    feels_max: float
    feels_avg: float
    max_wind_ms: float
    max_gusts_ms: float
    max_precip_prob: int
    total_precip_mm: float
    total_snow_cm: float
    max_uv: float
    avg_humidity: int
    alerts: WeatherAlerts


class OutfitAdvice(BaseModel):
    """Structured clothing recommendation returned by either the rules or AI engine."""

    headline: str
    top: str
    outerwear: str
    bottom: str
    footwear: str
    accessories: list[str] = Field(default_factory=list)
    pro_tip: str
    source: Literal["ai", "rules"] = "rules"
    model_name: str | None = None


TransportMode = Literal["walk", "bike", "transit", "car"]


class CommuteRoute(BaseModel):
    """User's recurring Home -> Destination commute settings."""

    enabled: bool = False
    destination_name: str | None = None
    dest_latitude: float | None = None
    dest_longitude: float | None = None
    dest_timezone: str | None = None
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    depart_hour: int = Field(default=8, ge=0, le=23)
    return_hour: int = Field(default=18, ge=0, le=23)
    transport_mode: TransportMode = "walk"

    @property
    def has_destination(self) -> bool:
        return self.dest_latitude is not None and self.dest_longitude is not None

    def is_active_on(self, weekday: int) -> bool:
        return self.enabled and self.has_destination and weekday in self.weekdays


class CommuteLegSummary(BaseModel):
    """Aggregated weather snapshot for one leg of the commute (there or back)."""

    hour: int
    temp: float
    apparent_temp: float
    wind_speed_ms: float
    wind_gusts_ms: float
    precip_prob: int
    precipitation_mm: float
    condition_emoji: str
    condition_text: str
    is_rain: bool


class CommuteSummary(BaseModel):
    """Full day commute weather comparison between origin and destination."""

    origin_name: str
    destination_name: str
    transport_mode: TransportMode
    way_there: CommuteLegSummary
    at_destination_temp_min: float
    at_destination_temp_max: float
    at_destination_condition_emoji: str
    at_destination_condition_text: str
    way_back: CommuteLegSummary
    rain_on_way_there: bool = False
    rain_on_way_back: bool = False
    wind_warning: bool = False
    same_location: bool = False
