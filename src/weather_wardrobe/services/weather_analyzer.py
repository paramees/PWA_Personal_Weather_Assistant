from __future__ import annotations

from datetime import date

from weather_wardrobe.models import (
    DayWeatherSummary,
    HourlyWeatherPoint,
    SlotSummary,
    WeatherAlerts,
)
from weather_wardrobe.services.open_meteo import describe_wmo_code


def _format_hour_ranges(hours: list[int]) -> str | None:
    """Collapse sorted hour integers into readable intervals, e.g. [14,15,16] -> '14:00–17:00'."""
    if not hours:
        return None
    unique_hours = sorted(set(hours))
    ranges: list[tuple[int, int]] = []
    start = prev = unique_hours[0]
    for hour in unique_hours[1:]:
        if hour == prev + 1:
            prev = hour
        else:
            ranges.append((start, prev))
            start = prev = hour
    ranges.append((start, prev))
    return ", ".join(f"{s:02d}:00–{e + 1:02d}:00" for s, e in ranges)


def is_rain_hour(point: HourlyWeatherPoint) -> bool:
    return (
        point.rain_mm >= 0.3
        or (point.precipitation_mm >= 0.3 and point.snowfall_cm == 0 and point.temp > 0.5)
        or (point.precip_prob >= 45 and point.temp > 0.5)
    )


def _pick_slot(points: list[HourlyWeatherPoint], target_hour: int, label: str) -> SlotSummary:
    chosen = min(points, key=lambda p: abs(p.time.hour - target_hour))
    emoji, text = describe_wmo_code(chosen.weather_code)
    return SlotSummary(
        label=label,
        hour=chosen.time.hour,
        temp=round(chosen.temp, 1),
        apparent_temp=round(chosen.apparent_temp, 1),
        weather_code=chosen.weather_code,
        condition_text=text,
        condition_emoji=emoji,
        wind_speed_ms=round(chosen.wind_speed_ms, 1),
        precip_prob=chosen.precip_prob,
    )


def analyze_day(
    hourly_points: list[HourlyWeatherPoint],
    target_date: date,
    city_name: str,
    timezone: str,
    active_start_hour: int = 8,
    active_end_hour: int = 21,
) -> DayWeatherSummary:
    """Deterministically aggregate hourly points into a day summary and safety alerts."""
    day_points = [p for p in hourly_points if p.time.date() == target_date]
    if not day_points:
        raise ValueError(f"No hourly forecast points available for {target_date.isoformat()}")

    window = [p for p in day_points if active_start_hour <= p.time.hour <= active_end_hour]
    if not window:
        window = day_points

    mid_hour = (active_start_hour + active_end_hour) // 2
    morning = _pick_slot(window, active_start_hour, "Утро")
    day = _pick_slot(window, mid_hour, "День")
    evening = _pick_slot(window, active_end_hour, "Вечер")

    temp_min = round(min(p.temp for p in window), 1)
    temp_max = round(max(p.temp for p in window), 1)
    feels_min = round(min(p.apparent_temp for p in window), 1)
    feels_max = round(max(p.apparent_temp for p in window), 1)
    feels_avg = round(sum(p.apparent_temp for p in window) / len(window), 1)

    max_wind_ms = round(max(p.wind_speed_ms for p in window), 1)
    max_gusts_ms = round(max(p.wind_gusts_ms for p in window), 1)
    max_precip_prob = max(p.precip_prob for p in window)
    total_precip_mm = round(sum(p.precipitation_mm for p in window), 1)
    total_snow_cm = round(sum(p.snowfall_cm for p in window), 1)
    max_uv = round(max(p.uv_index for p in window), 1)
    avg_humidity = round(sum(p.humidity for p in window) / len(window))

    rain_hours = [p.time.hour for p in window if is_rain_hour(p)]
    umbrella_required = len(rain_hours) > 0
    rain_window = _format_hour_ranges(rain_hours)

    snow_or_ice_risk = (total_snow_cm >= 0.2) or any(
        p.temp <= 1.0 and (p.precipitation_mm >= 0.2 or p.precip_prob >= 45) for p in window
    )
    strong_wind = (max_wind_ms >= 9.0) or (max_gusts_ms >= 13.0)
    temp_swing_delta = round(max(feels_max - feels_min, temp_max - temp_min), 1)
    big_temp_swing = temp_swing_delta >= 8.0
    high_uv = max_uv >= 5.0
    freezing_risk = feels_min <= 0.0
    heat_risk = feels_max >= 27.0

    alerts = WeatherAlerts(
        umbrella_required=umbrella_required,
        rain_window=rain_window,
        snow_or_ice_risk=snow_or_ice_risk,
        strong_wind=strong_wind,
        big_temp_swing=big_temp_swing,
        temp_swing_delta=temp_swing_delta,
        high_uv=high_uv,
        freezing_risk=freezing_risk,
        heat_risk=heat_risk,
    )

    return DayWeatherSummary(
        city_name=city_name,
        target_date=target_date,
        timezone=timezone,
        active_start_hour=active_start_hour,
        active_end_hour=active_end_hour,
        morning=morning,
        day=day,
        evening=evening,
        temp_min=temp_min,
        temp_max=temp_max,
        feels_min=feels_min,
        feels_max=feels_max,
        feels_avg=feels_avg,
        max_wind_ms=max_wind_ms,
        max_gusts_ms=max_gusts_ms,
        max_precip_prob=max_precip_prob,
        total_precip_mm=total_precip_mm,
        total_snow_cm=total_snow_cm,
        max_uv=max_uv,
        avg_humidity=avg_humidity,
        alerts=alerts,
    )
