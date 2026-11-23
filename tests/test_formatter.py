from __future__ import annotations

from datetime import date

from weather_wardrobe.models import (
    DaySchedule,
    DayWeatherSummary,
    OutfitAdvice,
    SlotSummary,
    UserProfile,
    WeatherAlerts,
)
from weather_wardrobe.services.formatter import (
    format_forecast_message,
    format_schedule_brief,
    format_settings_summary,
)


def _sample_summary() -> DayWeatherSummary:
    slot = SlotSummary(
        label="День",
        hour=14,
        temp=11.0,
        apparent_temp=8.0,
        weather_code=61,
        condition_text="Небольшой дождь",
        condition_emoji="🌦",
        wind_speed_ms=9.5,
        precip_prob=80,
    )
    return DayWeatherSummary(
        city_name="Berlin <Test & Co>",
        target_date=date(2026, 11, 23),
        timezone="Europe/Berlin",
        active_start_hour=8,
        active_end_hour=21,
        morning=slot.model_copy(update={"label": "Утро", "hour": 8}),
        day=slot,
        evening=slot.model_copy(update={"label": "Вечер", "hour": 21}),
        temp_min=7.0,
        temp_max=15.0,
        feels_min=5.0,
        feels_max=14.0,
        feels_avg=9.0,
        max_wind_ms=9.5,
        max_gusts_ms=14.0,
        max_precip_prob=80,
        total_precip_mm=2.5,
        total_snow_cm=0.0,
        max_uv=2.0,
        avg_humidity=78,
        alerts=WeatherAlerts(
            umbrella_required=True,
            rain_window="14:00–16:00",
            strong_wind=True,
            big_temp_swing=True,
            temp_swing_delta=9.0,
        ),
    )


def test_format_forecast_escapes_html_and_renders_badges() -> None:
    summary = _sample_summary()
    ai_advice = OutfitAdvice(
        headline="Свежо & ветрено <осторожно>",
        top="Худи",
        outerwear="Ветровка",
        bottom="Джинсы",
        footwear="Кроссовки",
        accessories=["☂️ Зонт (дождь 14:00–16:00)"],
        pro_tip="Возьми зонт > не промокнешь.",
        source="ai",
        model_name="llama-3.3-70b",
    )

    msg = format_forecast_message(summary, ai_advice, is_tomorrow=False)

    assert "Berlin &lt;Test &amp; Co&gt;" in msg
    assert "Свежо &amp; ветрено &lt;осторожно&gt;" in msg
    assert "Возьми зонт &gt; не промокнешь." in msg
    assert "ВОЗЬМИ ЗОНТ!" in msg
    assert "Перепад температур 9°C" in msg
    assert "Подобрано ИИ (llama-3.3-70b)" in msg

    rules_advice = ai_advice.model_copy(update={"source": "rules", "model_name": None})
    rules_msg = format_forecast_message(summary, rules_advice, is_tomorrow=True)
    assert "Погода на завтра" in rules_msg
    assert "Подобрано метео-алгоритмом" in rules_msg


def test_format_schedule_brief_groups_days() -> None:
    all_off = [DaySchedule(weekday=i, enabled=False, send_time="08:00") for i in range(7)]
    assert format_schedule_brief(all_off) == "выключена"

    mixed = [
        DaySchedule(weekday=0, enabled=True, send_time="07:30"),
        DaySchedule(weekday=1, enabled=True, send_time="07:30"),
        DaySchedule(weekday=2, enabled=True, send_time="07:30"),
        DaySchedule(weekday=3, enabled=True, send_time="07:30"),
        DaySchedule(weekday=4, enabled=True, send_time="07:30"),
        DaySchedule(weekday=5, enabled=True, send_time="10:00"),
        DaySchedule(weekday=6, enabled=False, send_time="08:00"),
    ]
    assert format_schedule_brief(mixed) == "Пн–Пт 07:30 · Сб 10:00"


def test_format_settings_summary_renders_safe_html() -> None:
    user = UserProfile(
        user_id=1,
        city_name="Москва",
        latitude=55.75,
        longitude=37.61,
        timezone="Europe/Moscow",
        comfort_offset=-2,
        wardrobe_text="Пальто <шерсть> & кроссовки",
        use_ai=True,
    )
    schedules = [DaySchedule(weekday=0, enabled=True, send_time="08:00")]
    text = format_settings_summary(user, schedules, llm_configured=True, llm_model="gemini-4")
    assert "Пальто &lt;шерсть&gt; &amp; кроссовки" in text
    assert "-2°C (быстро мёрзну)" in text
    assert "включён (gemini-4)" in text
