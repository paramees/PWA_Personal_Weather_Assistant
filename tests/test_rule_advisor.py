from __future__ import annotations

from datetime import date

from weather_wardrobe.models import (
    CommuteLegSummary,
    CommuteSummary,
    DayWeatherSummary,
    SlotSummary,
    UserProfile,
    WeatherAlerts,
)
from weather_wardrobe.services.rule_advisor import RuleBasedAdvisor


def _make_summary(
    *,
    feels_min: float = 10.0,
    feels_max: float = 15.0,
    feels_avg: float = 12.0,
    umbrella: bool = False,
    rain_window: str | None = None,
    strong_wind: bool = False,
    high_uv: bool = False,
    snow_or_ice: bool = False,
    big_swing: bool = False,
) -> DayWeatherSummary:
    slot = SlotSummary(
        label="День",
        hour=14,
        temp=feels_avg + 1,
        apparent_temp=feels_avg,
        weather_code=1,
        condition_text="Преимущественно ясно",
        condition_emoji="🌤",
        wind_speed_ms=3.0,
        precip_prob=10,
    )
    return DayWeatherSummary(
        city_name="Berlin",
        target_date=date(2026, 11, 24),
        timezone="Europe/Berlin",
        active_start_hour=8,
        active_end_hour=21,
        morning=slot.model_copy(update={"label": "Утро", "hour": 8}),
        day=slot,
        evening=slot.model_copy(update={"label": "Вечер", "hour": 21}),
        temp_min=feels_min + 1,
        temp_max=feels_max + 1,
        feels_min=feels_min,
        feels_max=feels_max,
        feels_avg=feels_avg,
        max_wind_ms=11.0 if strong_wind else 3.0,
        max_gusts_ms=15.0 if strong_wind else 5.0,
        max_precip_prob=80 if umbrella else 10,
        total_precip_mm=3.0 if umbrella else 0.0,
        total_snow_cm=1.0 if snow_or_ice else 0.0,
        max_uv=6.5 if high_uv else 1.5,
        avg_humidity=65,
        alerts=WeatherAlerts(
            umbrella_required=umbrella,
            rain_window=rain_window,
            snow_or_ice_risk=snow_or_ice,
            strong_wind=strong_wind,
            big_temp_swing=big_swing,
            temp_swing_delta=10.0 if big_swing else 4.0,
            high_uv=high_uv,
            freezing_risk=feels_min <= 0.0,
            heat_risk=feels_max >= 27.0,
        ),
    )


def test_rule_advisor_freezing_vs_hot_bands() -> None:
    advisor = RuleBasedAdvisor()
    user = UserProfile(user_id=1, comfort_offset=0)

    cold_advice = advisor.advise(_make_summary(feels_min=-15, feels_max=-8, feels_avg=-12), user)
    assert cold_advice.source == "rules"
    assert "пуховик" in cold_advice.outerwear.lower()
    assert any("перчатки" in item.lower() for item in cold_advice.accessories)

    hot_advice = advisor.advise(_make_summary(feels_min=22, feels_max=29, feels_avg=26), user)
    assert "не нужна" in hot_advice.outerwear.lower()
    assert "шорты" in hot_advice.bottom.lower()


def test_comfort_offset_shifts_outfit_recommendation() -> None:
    advisor = RuleBasedAdvisor()
    summary = _make_summary(feels_min=13, feels_max=17, feels_avg=15)

    chilly_user = UserProfile(user_id=1, comfort_offset=-5)
    warm_user = UserProfile(user_id=2, comfort_offset=5)

    chilly_advice = advisor.advise(summary, chilly_user)
    warm_advice = advisor.advise(summary, warm_user)

    assert chilly_advice.outerwear != warm_advice.outerwear
    outer_lower = chilly_advice.outerwear.lower()
    assert "ветровка" in outer_lower or "тренч" in outer_lower
    assert "не требуется" in warm_advice.outerwear.lower()


def test_rain_and_high_uv_modifiers() -> None:
    advisor = RuleBasedAdvisor()
    user = UserProfile(user_id=1, comfort_offset=0)
    summary = _make_summary(
        feels_min=23,
        feels_max=27,
        feels_avg=25,
        umbrella=True,
        rain_window="15:00–17:00",
        high_uv=True,
    )

    advice = advisor.advise(summary, user)

    assert any("зонт" in item.lower() and "15:00–17:00" in item for item in advice.accessories)
    assert any("очки" in item.lower() or "spf" in item.lower() for item in advice.accessories)
    assert "без замши" in advice.footwear.lower()
    assert "дождевик" in advice.outerwear.lower()


def test_bike_commute_rain_recommends_raincoat_instead_of_umbrella() -> None:
    advisor = RuleBasedAdvisor()
    user = UserProfile(user_id=1)
    summary = _make_summary(
        feels_min=9,
        feels_max=12,
        feels_avg=10,
        umbrella=True,
        rain_window="18:00–19:00",
    )
    leg = CommuteLegSummary(
        hour=8,
        temp=10.0,
        apparent_temp=9.0,
        wind_speed_ms=7.5,
        wind_gusts_ms=11.0,
        precip_prob=10,
        precipitation_mm=0.0,
        condition_emoji="⛅",
        condition_text="Облачно",
        is_rain=False,
    )
    commute = CommuteSummary(
        origin_name="Дом",
        destination_name="Офис",
        transport_mode="bike",
        way_there=leg,
        at_destination_temp_min=11.0,
        at_destination_temp_max=13.0,
        at_destination_condition_emoji="⛅",
        at_destination_condition_text="Облачно",
        way_back=leg.model_copy(update={"hour": 18, "is_rain": True, "precip_prob": 80}),
        rain_on_way_there=False,
        rain_on_way_back=True,
        wind_warning=True,
    )

    advice = advisor.advise(summary, user, commute=commute)

    assert any("дождевик" in item.lower() for item in advice.accessories)
    assert not any("зонт" in item.lower() for item in advice.accessories)
    assert "дождь" in advice.pro_tip.lower()
