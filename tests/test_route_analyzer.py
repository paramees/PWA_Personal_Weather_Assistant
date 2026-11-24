from __future__ import annotations

from datetime import date, datetime

from weather_wardrobe.models import CommuteRoute, HourlyWeatherPoint
from weather_wardrobe.services.route_analyzer import analyze_commute, approx_distance_km


def _make_points(
    target_date: date,
    *,
    temp: float = 12.0,
    apparent_temp: float = 10.0,
    wind: float = 3.0,
    gusts: float = 5.0,
    overrides: dict[int, dict[str, float | int]] | None = None,
) -> list[HourlyWeatherPoint]:
    overrides = overrides or {}
    points: list[HourlyWeatherPoint] = []
    for hour in range(24):
        ov = overrides.get(hour, {})
        points.append(
            HourlyWeatherPoint(
                time=datetime(target_date.year, target_date.month, target_date.day, hour, 0),
                temp=float(ov.get("temp", temp)),
                apparent_temp=float(ov.get("apparent_temp", apparent_temp)),
                humidity=65,
                precip_prob=int(ov.get("precip_prob", 10)),
                precipitation_mm=float(ov.get("precipitation_mm", 0.0)),
                rain_mm=float(ov.get("rain_mm", 0.0)),
                snowfall_cm=0.0,
                weather_code=int(ov.get("weather_code", 1)),
                wind_speed_ms=float(ov.get("wind_speed_ms", wind)),
                wind_gusts_ms=float(ov.get("wind_gusts_ms", gusts)),
                uv_index=1.0,
            )
        )
    return points


def test_analyze_commute_dry_morning_rain_evening() -> None:
    target = date(2026, 11, 24)
    home = _make_points(target, temp=10.0, apparent_temp=9.0)
    dest = _make_points(
        target,
        temp=13.0,
        apparent_temp=12.0,
        overrides={
            12: {"temp": 16.0, "apparent_temp": 15.0, "weather_code": 0},
            18: {
                "temp": 8.0,
                "apparent_temp": 5.0,
                "rain_mm": 1.4,
                "precipitation_mm": 1.4,
                "precip_prob": 80,
                "weather_code": 63,
            },
        },
    )
    route = CommuteRoute(
        enabled=True,
        destination_name="Офис",
        dest_latitude=52.53,
        dest_longitude=13.42,
        weekdays=[0, 1, 2, 3, 4],
        depart_hour=8,
        return_hour=18,
        transport_mode="walk",
    )

    commute = analyze_commute(home, dest, target, "Дом", route)

    assert commute.rain_on_way_there is False
    assert commute.rain_on_way_back is True
    assert commute.way_back.temp == 8.0
    assert commute.at_destination_temp_min == 13.0
    assert commute.at_destination_temp_max == 16.0


def test_analyze_commute_cyclist_lower_wind_threshold() -> None:
    target = date(2026, 11, 24)
    pts = _make_points(target, wind=7.5, gusts=9.0)
    bike_route = CommuteRoute(
        enabled=True,
        destination_name="Офис",
        dest_latitude=52.53,
        dest_longitude=13.42,
        depart_hour=8,
        return_hour=18,
        transport_mode="bike",
    )
    walk_route = bike_route.model_copy(update={"transport_mode": "walk"})

    bike_commute = analyze_commute(pts, pts, target, "Дом", bike_route)
    walk_commute = analyze_commute(pts, pts, target, "Дом", walk_route)

    assert bike_commute.wind_warning is True
    assert walk_commute.wind_warning is False


def test_approx_distance_km() -> None:
    # Berlin to Munich ~ 504 km
    assert approx_distance_km(52.52, 13.405, 48.135, 11.582) > 450.0
    # Nearby blocks < 1 km
    assert approx_distance_km(52.520, 13.405, 52.524, 13.410) < 1.0
