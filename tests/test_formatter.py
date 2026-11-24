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
    format_advanced_settings_summary,
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
        city_name="Berlin <Test & Co>, Germany",
        target_date=date(2026, 11, 23),
        timezone="Europe/Berlin",
        active_start_hour=8,
        active_end_hour=21,
        morning=slot.model_copy(update={"label": "Утро", "hour": 8, "precip_prob": 20}),
        day=slot,
        evening=slot.model_copy(update={"label": "Вечер", "hour": 21, "precip_prob": 50}),
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


def test_format_forecast_compact_escapes_html_and_renders_sections() -> None:
    summary = _sample_summary()
    advice = OutfitAdvice(
        headline="Ветрено & дождь",
        top="Худи",
        outerwear="Ветровка",
        bottom="Джинсы",
        footwear="Кроссовки",
        accessories=["☂️ Зонт"],
        pro_tip="Возьми дождевик > не промокнешь.",
        source="ai",
        model_name="llama-3.3-70b",
    )

    msg = format_forecast_message(summary, advice, is_tomorrow=False)

    assert "Berlin &lt;Test &amp; Co&gt;" in msg
    assert "Возьми дождевик &gt; не промокнешь." in msg
    assert "ВОЗЬМИ ЗОНТ!" in msg
    assert "Перепад 9°C" in msg
    assert "• Утро: <b>+11°</b> (ощущ. +8°)" in msg
    assert "• День: <b>+11°</b> (ощущ. +8°) · 🌦, 🌧 80%" in msg
    assert "• Вечер: <b>+11°</b> (ощущ. +8°) · 🌦, 🌧 50%" in msg
    assert "👕 <b>Что надеть</b> — <i>Ветрено &amp; дождь</i>" in msg
    assert "• <b>Верх:</b> Ветровка + Худи" in msg
    assert "• <b>Низ:</b> Джинсы" in msg
    assert "• <b>Обувь:</b> Кроссовки" in msg
    assert "• <b>С собой:</b> ☂️ Зонт" in msg
    assert "Маршрут" not in msg
    assert "Подобрано ИИ" not in msg

    tomorrow_msg = format_forecast_message(summary, advice, is_tomorrow=True)
    assert "(завтра)" in tomorrow_msg


def test_format_schedule_brief() -> None:
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


def test_format_settings_and_advanced_summaries() -> None:
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

    main_text = format_settings_summary(user, schedules)
    assert "Пальто &lt;шерсть&gt; &amp; кроссовки" in main_text
    assert "Утренняя рассылка:" in main_text
    assert "Маршрут" not in main_text

    adv_text = format_advanced_settings_summary(user, llm_configured=True, llm_model="llama-3.3")
    assert "-2°C (быстро мёрзну)" in adv_text
    assert "включён (llama-3.3)" in adv_text
