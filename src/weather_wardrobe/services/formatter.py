from __future__ import annotations

import html

from weather_wardrobe.models import (
    DaySchedule,
    DayWeatherSummary,
    OutfitAdvice,
    SlotSummary,
    UserProfile,
)

WEEKDAY_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
WEEKDAY_FULL = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
]


def _fmt_short_temp(value: float) -> str:
    rounded = int(round(value))
    if rounded > 0:
        return f"+{rounded}°"
    return f"{rounded}°"


def _short_place(name: str) -> str:
    first = name.split(",")[0].strip()
    return first or name


def format_comfort_label(offset: int) -> str:
    if offset <= -2:
        return f"{offset:+d}°C (быстро мёрзну)"
    if offset == -1:
        return "-1°C (слегка мёрзну)"
    if offset == 0:
        return "0°C (стандарт)"
    if offset == 1:
        return "+1°C (слегка жарко)"
    return f"{offset:+d}°C (часто жарко)"


def format_schedule_brief(schedules: list[DaySchedule]) -> str:
    """Group consecutive enabled weekdays with identical time into a compact label."""
    ordered = sorted(schedules, key=lambda s: s.weekday)
    enabled_days = [s for s in ordered if s.enabled]
    if not enabled_days:
        return "выключена"

    groups: list[tuple[int, int, str]] = []
    for item in enabled_days:
        if groups and groups[-1][1] == item.weekday - 1 and groups[-1][2] == item.send_time:
            start, _, send_time = groups[-1]
            groups[-1] = (start, item.weekday, send_time)
        else:
            groups.append((item.weekday, item.weekday, item.send_time))

    parts: list[str] = []
    for start, end, send_time in groups:
        if start == end:
            day_part = WEEKDAY_SHORT[start]
        else:
            day_part = f"{WEEKDAY_SHORT[start]}–{WEEKDAY_SHORT[end]}"
        parts.append(f"{day_part} {send_time}")
    return " · ".join(parts)


def _format_slot_line(slot: SlotSummary) -> str:
    rain_suffix = f", 🌧 {slot.precip_prob}%" if slot.precip_prob >= 40 else ""
    return (
        f"• {html.escape(slot.label)}: <b>{_fmt_short_temp(slot.temp)}</b> "
        f"(ощущ. {_fmt_short_temp(slot.apparent_temp)}) · {slot.condition_emoji}{rain_suffix}"
    )


def format_forecast_message(
    summary: DayWeatherSummary,
    advice: OutfitAdvice,
    is_tomorrow: bool = False,
) -> str:
    """Render a compact, mobile-first Telegram HTML forecast & outfit card."""
    short_city = html.escape(_short_place(summary.city_name))
    weekday_name = WEEKDAY_SHORT[summary.target_date.weekday()]
    date_str = summary.target_date.strftime("%d.%m")
    tomorrow_tag = " (завтра)" if is_tomorrow else ""

    m, d, e = summary.morning, summary.day, summary.evening
    lines: list[str] = [
        f"📍 <b>{short_city}</b> · {weekday_name}, {date_str}{tomorrow_tag}",
        (
            f"{d.condition_emoji} {html.escape(d.condition_text)} · "
            f"💨 до {summary.max_wind_ms:.0f} м/с · 🌧 {summary.max_precip_prob}%"
        ),
    ]

    alerts = summary.alerts
    alert_lines: list[str] = []

    if alerts.umbrella_required:
        rain_info = f" ({html.escape(alerts.rain_window)})" if alerts.rain_window else ""
        alert_lines.append(
            f"☔️ <b>ВОЗЬМИ ЗОНТ!</b> Дождь{rain_info} · до {summary.max_precip_prob}%"
        )
    if alerts.snow_or_ice_risk:
        alert_lines.append("❄️ <b>Снег / гололёд:</b> осторожнее на улице")
    if alerts.big_temp_swing:
        alert_lines.append(
            f"⚠️ <b>Перепад {alerts.temp_swing_delta:g}°C:</b> одевайся слоями"
        )
    if alerts.strong_wind:
        alert_lines.append(f"💨 <b>Сильный ветер:</b> до {summary.max_wind_ms:.0f} м/с")
    if alerts.high_uv:
        alert_lines.append(f"🕶 <b>Высокий УФ ({summary.max_uv:.0f}):</b> очки и SPF")

    if alert_lines:
        lines.append("")
        lines.extend(alert_lines)

    lines.append("")
    lines.append(_format_slot_line(m))
    lines.append(_format_slot_line(d))
    lines.append(_format_slot_line(e))

    if advice.outerwear.lower().startswith(("не нуж", "днём не треб")):
        top_text = html.escape(advice.top)
    else:
        top_text = f"{html.escape(advice.outerwear)} + {html.escape(advice.top)}"

    headline_part = f" — <i>{html.escape(advice.headline)}</i>" if advice.headline.strip() else ""

    lines.append("")
    lines.append(f"👕 <b>Что надеть</b>{headline_part}")
    lines.append(f"• <b>Верх:</b> {top_text}")
    lines.append(f"• <b>Низ:</b> {html.escape(advice.bottom)}")
    lines.append(f"• <b>Обувь:</b> {html.escape(advice.footwear)}")
    if advice.accessories:
        acc_str = ", ".join(html.escape(item) for item in advice.accessories)
        lines.append(f"• <b>С собой:</b> {acc_str}")

    lines.append("")
    lines.append(f"💡 <i>{html.escape(advice.pro_tip)}</i>")
    return "\n".join(lines)


def format_settings_summary(
    user: UserProfile,
    schedules: list[DaySchedule],
    llm_configured: bool = False,
    llm_model: str = "",
) -> str:
    """Render the compact /settings overview screen."""
    del llm_configured, llm_model
    city = html.escape(_short_place(user.city_name)) if user.city_name else "не выбран"
    schedule_str = html.escape(format_schedule_brief(schedules))

    if user.wardrobe_text:
        preview = user.wardrobe_text.strip()
        if len(preview) > 60:
            preview = preview[:57] + "..."
        wardrobe_str = html.escape(preview)
    else:
        wardrobe_str = "не задан"

    return "\n".join(
        [
            "⚙️ <b>Настройки</b>",
            "",
            f"📍 <b>Город:</b> {city}",
            f"🗓 <b>Утренняя рассылка:</b> {schedule_str}",
            f"🧥 <b>Гардероб:</b> {wardrobe_str}",
        ]
    )


def format_advanced_settings_summary(
    user: UserProfile,
    llm_configured: bool,
    llm_model: str,
) -> str:
    """Render secondary tuning options under 'Ещё настройки'."""
    tz = html.escape(user.timezone)
    comfort_str = html.escape(format_comfort_label(user.comfort_offset))
    if not llm_configured:
        ai_status = "не настроен ключ API"
    elif user.use_ai:
        ai_status = f"включён ({html.escape(llm_model)})"
    else:
        ai_status = "выключен (работают правила)"

    return "\n".join(
        [
            "🔧 <b>Дополнительные настройки</b>",
            "",
            f"🕒 <b>Часовой пояс:</b> {tz}",
            (
                f"🌅 <b>Активное окно дня:</b> "
                f"{user.active_start_hour:02d}:00–{user.active_end_hour:02d}:00"
            ),
            f"🌡 <b>Термокомфорт:</b> {comfort_str}",
            f"🤖 <b>ИИ-стилист:</b> {ai_status}",
        ]
    )
