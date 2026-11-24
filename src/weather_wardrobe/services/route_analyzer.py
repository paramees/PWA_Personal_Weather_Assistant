from __future__ import annotations

import logging
import math
from datetime import date

import httpx

from weather_wardrobe.models import (
    CommuteLegSummary,
    CommuteRoute,
    CommuteSummary,
    HourlyWeatherPoint,
    UserProfile,
)
from weather_wardrobe.services.open_meteo import OpenMeteoClient, describe_wmo_code
from weather_wardrobe.services.weather_analyzer import is_rain_hour

logger = logging.getLogger(__name__)


def approx_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate approximate great-circle distance in kilometers (haversine)."""
    r_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return 2 * r_km * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _slice_leg_points(
    points: list[HourlyWeatherPoint],
    target_date: date,
    target_hour: int,
) -> list[HourlyWeatherPoint]:
    day_pts = [p for p in points if p.time.date() == target_date]
    if not day_pts:
        return []
    hours = {target_hour, min(23, target_hour + 1)}
    window = [p for p in day_pts if p.time.hour in hours]
    if window:
        return window
    return [min(day_pts, key=lambda p: abs(p.time.hour - target_hour))]


def _summarize_leg(
    home_points: list[HourlyWeatherPoint],
    dest_points: list[HourlyWeatherPoint],
    target_date: date,
    target_hour: int,
) -> CommuteLegSummary:
    home_leg = _slice_leg_points(home_points, target_date, target_hour)
    dest_leg = _slice_leg_points(dest_points, target_date, target_hour)
    combined = home_leg + dest_leg
    if not combined:
        raise ValueError(f"No commute points for {target_date.isoformat()}")

    colder = min(combined, key=lambda p: p.apparent_temp)
    rain_pts = [p for p in combined if is_rain_hour(p)]
    if rain_pts:
        rep = max(rain_pts, key=lambda p: (p.precipitation_mm, p.precip_prob))
    else:
        rep = min(combined, key=lambda p: abs(p.time.hour - target_hour))
    emoji, text = describe_wmo_code(rep.weather_code)

    return CommuteLegSummary(
        hour=target_hour,
        temp=round(colder.temp, 1),
        apparent_temp=round(colder.apparent_temp, 1),
        wind_speed_ms=round(max(p.wind_speed_ms for p in combined), 1),
        wind_gusts_ms=round(max(p.wind_gusts_ms for p in combined), 1),
        precip_prob=max(p.precip_prob for p in combined),
        precipitation_mm=round(max(p.precipitation_mm for p in combined), 1),
        condition_emoji=emoji,
        condition_text=text,
        is_rain=bool(rain_pts),
    )


def analyze_commute(
    home_points: list[HourlyWeatherPoint],
    dest_points: list[HourlyWeatherPoint],
    target_date: date,
    origin_name: str,
    route: CommuteRoute,
    *,
    same_location: bool | None = None,
) -> CommuteSummary:
    """Analyze morning trip, destination daytime range, and evening return trip."""
    way_there = _summarize_leg(home_points, dest_points, target_date, route.depart_hour)
    way_back = _summarize_leg(dest_points, home_points, target_date, route.return_hour)

    dest_day = [p for p in dest_points if p.time.date() == target_date]
    stay_pts = [
        p
        for p in dest_day
        if route.depart_hour + 1 <= p.time.hour <= route.return_hour - 1
    ]
    if not stay_pts:
        stay_pts = [
            p for p in dest_day if route.depart_hour <= p.time.hour <= route.return_hour
        ]
    if not stay_pts:
        stay_pts = dest_day

    mid_hour = (route.depart_hour + route.return_hour) // 2
    mid_pt = min(stay_pts, key=lambda p: abs(p.time.hour - mid_hour))
    dest_emoji, dest_text = describe_wmo_code(mid_pt.weather_code)

    max_wind = max(way_there.wind_speed_ms, way_back.wind_speed_ms)
    max_gusts = max(way_there.wind_gusts_ms, way_back.wind_gusts_ms)
    if route.transport_mode == "bike":
        wind_warning = max_wind >= 7.0 or max_gusts >= 10.0
    else:
        wind_warning = max_wind >= 9.0 or max_gusts >= 13.0

    is_same = (dest_points is home_points) if same_location is None else same_location

    return CommuteSummary(
        origin_name=origin_name,
        destination_name=route.destination_name or "Точка Б",
        transport_mode=route.transport_mode,
        way_there=way_there,
        at_destination_temp_min=round(min(p.temp for p in stay_pts), 1),
        at_destination_temp_max=round(max(p.temp for p in stay_pts), 1),
        at_destination_condition_emoji=dest_emoji,
        at_destination_condition_text=dest_text,
        way_back=way_back,
        rain_on_way_there=way_there.is_rain,
        rain_on_way_back=way_back.is_rain,
        wind_warning=wind_warning,
        same_location=is_same,
    )


async def compute_day_commute(
    weather_client: OpenMeteoClient,
    user: UserProfile,
    route: CommuteRoute,
    home_points: list[HourlyWeatherPoint],
    target_date: date,
) -> CommuteSummary | None:
    """Compute commute weather summary if the route is active on target_date."""
    if not route.is_active_on(target_date.weekday()):
        return None
    if not user.has_location or not route.has_destination:
        return None

    assert user.latitude is not None and user.longitude is not None
    assert route.dest_latitude is not None and route.dest_longitude is not None

    dist_km = approx_distance_km(
        user.latitude,
        user.longitude,
        route.dest_latitude,
        route.dest_longitude,
    )
    same_loc = dist_km < 1.0

    if same_loc:
        dest_points = home_points
    else:
        try:
            _, dest_points = await weather_client.fetch_forecast(
                route.dest_latitude,
                route.dest_longitude,
                days=2,
            )
        except httpx.HTTPError as exc:
            logger.warning("Destination forecast failed (%s); skipping route block.", exc)
            return None

    try:
        return analyze_commute(
            home_points=home_points,
            dest_points=dest_points,
            target_date=target_date,
            origin_name=user.city_name or "Дом",
            route=route,
            same_location=same_loc,
        )
    except ValueError as exc:
        logger.warning("Route analysis skipped (%s).", exc)
        return None
