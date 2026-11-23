from __future__ import annotations

from datetime import date, datetime

import pytest

from weather_wardrobe.models import HourlyWeatherPoint
from weather_wardrobe.services.weather_analyzer import analyze_day


def _make_day_points(
    target_date: date,
    *,
    base_temp: float = 12.0,
    base_feels: float = 10.0,
    overrides: dict[int, dict[str, float | int]] | None = None,
) -> list[HourlyWeatherPoint]:
    overrides = overrides or {}
    points: list[HourlyWeatherPoint] = []
    for hour in range(24):
        ov = overrides.get(hour, {})
        points.append(
            HourlyWeatherPoint(
                time=datetime(target_date.year, target_date.month, target_date.day, hour, 0),
                temp=float(ov.get("temp", base_temp)),
                apparent_temp=float(ov.get("apparent_temp", base_feels)),
                humidity=int(ov.get("humidity", 60)),
                precip_prob=int(ov.get("precip_prob", 5)),
                precipitation_mm=float(ov.get("precipitation_mm", 0.0)),
                rain_mm=float(ov.get("rain_mm", 0.0)),
                snowfall_cm=float(ov.get("snowfall_cm", 0.0)),
                weather_code=int(ov.get("weather_code", 1)),
                wind_speed_ms=float(ov.get("wind_speed_ms", 3.0)),
                wind_gusts_ms=float(ov.get("wind_gusts_ms", 5.0)),
                uv_index=float(ov.get("uv_index", 1.5)),
            )
        )
    return points


def test_rain_window_merging_and_umbrella_alert() -> None:
    target = date(2026, 11, 24)
    points = _make_day_points(
        target,
        overrides={
            9: {"rain_mm": 0.5, "precipitation_mm": 0.5, "precip_prob": 60, "weather_code": 61},
            10: {"rain_mm": 0.8, "precipitation_mm": 0.8, "precip_prob": 75, "weather_code": 63},
            14: {"rain_mm": 0.4, "precipitation_mm": 0.4, "precip_prob": 50, "weather_code": 61},
            15: {"rain_mm": 1.2, "precipitation_mm": 1.2, "precip_prob": 85, "weather_code": 63},
            16: {"rain_mm": 0.6, "precipitation_mm": 0.6, "precip_prob": 65, "weather_code": 61},
        },
    )

    summary = analyze_day(points, target, "Berlin", "Europe/Berlin", 8, 21)

    assert summary.alerts.umbrella_required is True
    assert summary.alerts.rain_window == "09:00–11:00, 14:00–17:00"
    assert summary.max_precip_prob == 85
    assert summary.total_precip_mm == pytest.approx(3.5)


def test_big_temperature_swing_and_active_window_excludes_night_frost() -> None:
    target = date(2026, 11, 24)
    points = _make_day_points(
        target,
        base_temp=14.0,
        base_feels=13.0,
        overrides={
            3: {"temp": -4.0, "apparent_temp": -7.0},
            8: {"temp": 8.0, "apparent_temp": 6.0},
            14: {"temp": 18.0, "apparent_temp": 17.5},
            21: {"temp": 9.0, "apparent_temp": 7.0},
        },
    )

    summary = analyze_day(points, target, "Berlin", "Europe/Berlin", 8, 21)

    assert summary.alerts.freezing_risk is False
    assert summary.alerts.big_temp_swing is True
    assert summary.alerts.temp_swing_delta == pytest.approx(11.5)
    assert summary.morning.hour == 8
    assert summary.day.hour == 14
    assert summary.evening.hour == 21


def test_strong_wind_and_snow_ice_detection() -> None:
    target = date(2026, 11, 24)
    points = _make_day_points(
        target,
        base_temp=0.5,
        base_feels=-4.0,
        overrides={
            12: {
                "temp": 0.2,
                "apparent_temp": -5.0,
                "snowfall_cm": 0.5,
                "precipitation_mm": 0.6,
                "precip_prob": 70,
                "wind_speed_ms": 9.5,
                "wind_gusts_ms": 15.0,
                "weather_code": 73,
            }
        },
    )

    summary = analyze_day(points, target, "Moscow", "Europe/Moscow", 8, 21)

    assert summary.alerts.snow_or_ice_risk is True
    assert summary.alerts.strong_wind is True
    assert summary.alerts.freezing_risk is True
    assert summary.alerts.umbrella_required is False


def test_analyze_day_raises_when_target_date_missing() -> None:
    target = date(2026, 11, 24)
    points = _make_day_points(target)
    with pytest.raises(ValueError, match="2026-11-25"):
        analyze_day(points, date(2026, 11, 25), "Berlin", "Europe/Berlin")
