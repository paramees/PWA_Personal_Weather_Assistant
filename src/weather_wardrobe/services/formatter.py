from __future__ import annotations

import html

from weather_wardrobe.models import (
    DaySchedule,
    DayWeatherSummary,
    OutfitAdvice,
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


def _fmt_temp(value: float) -> str:
    rounded = int(round(value))
    if rounded > 0:
        return f"+{rounded}°C"
    return f"{rounded}°C"


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


def format_forecast_message(
    summary: DayWeatherSummary,
    advice: OutfitAdvice,
    is_tomorrow: bool = False,
) -> str:
    """Render a Telegram HTML message with alerts, slot breakdown, and outfit advice."""
    city = html.escape(summary.city_name)
    day_word = "завтра" if is_tomorrow else "сегодня"
    weekday_name = WEEKDAY_SHORT[summary.target_date.weekday()]
    date_str = summary.target_date.strftime("%d.%m")

    lines: list[str] = [
        f"📍 <b>{city}</b> · Погода на {day_word} ({weekday_name}, {date_str})",
    ]

    alerts = summary.alerts
    alert_lines: list[str] = []
    if alerts.umbrella_required:
        rain_window = f" ({html.escape(alerts.rain_window)})" if alerts.rain_window else ""
        alert_lines.append(
            f"☔️ <b>ВОЗЬМИ ЗОНТ!</b> Дождь{rain_window} · шанс до {summary.max_precip_prob}%"
        )
    if alerts.snow_or_ice_risk:
        alert_lines.append("❄️ <b>Снег / гололёд:</b> выбирай обувь с цепкой подошвой")
    if alerts.big_temp_swing:
        alert_lines.append(
            f"⚠️ <b>Перепад температур {alerts.temp_swing_delta:g}°C:</b> одевайся слоями"
        )
    if alerts.strong_wind:
        alert_lines.append(
            f"💨 <b>Сильный ветер:</b> до {summary.max_wind_ms:.0f} м/с "
            f"(порывы {summary.max_gusts_ms:.0f} м/с)"
        )
    if alerts.high_uv:
        alert_lines.append(f"🕶 <b>Высокий УФ ({summary.max_uv:.0f}):</b> пригодятся очки и SPF")

    if alert_lines:
        lines.append("")
        lines.extend(alert_lines)

    slot_icons = {"Утро": "🌅", "День": "☀️", "Вечер": "🌆"}
    lines.append("")
    for slot in (summary.morning, summary.day, summary.evening):
        icon = slot_icons.get(slot.label, "•")
        cond = html.escape(slot.condition_text)
        lines.append(
            f"{icon} <b>{slot.label} ({slot.hour:02d}:00):</b> "
            f"{_fmt_temp(slot.temp)} <i>(ощущ. {_fmt_temp(slot.apparent_temp)})</i>, "
            f"{slot.condition_emoji} {cond}"
        )

    lines.append(
        f"💨 Ветер до {summary.max_wind_ms:.0f} м/с · "
        f"💧 Влажность {summary.avg_humidity}% · "
        f"🌧 Осадки до {summary.max_precip_prob}%"
    )

    lines.append("")
    lines.append(f"👕 <b>Что надеть — {html.escape(advice.headline)}</b>")
    lines.append(f"• <b>Верх:</b> {html.escape(advice.top)}")
    lines.append(f"• <b>Верхняя одежда:</b> {html.escape(advice.outerwear)}")
    lines.append(f"• <b>Низ:</b> {html.escape(advice.bottom)}")
    lines.append(f"• <b>Обувь:</b> {html.escape(advice.footwear)}")

    if advice.accessories:
        acc_str = ", ".join(html.escape(item) for item in advice.accessories)
        lines.append(f"• <b>С собой:</b> {acc_str}")

    lines.append("")
    lines.append(f"💡 <i>{html.escape(advice.pro_tip)}</i>")

    if advice.source == "ai":
        model_label = html.escape(advice.model_name or "LLM")
        footer = f"🤖 <i>Подобрано ИИ ({model_label}) + метео-правилами</i>"
    else:
        footer = "📐 <i>Подобрано метео-алгоритмом (правила)</i>"
    lines.append(footer)

    return "\n".join(lines)


def format_settings_summary(
    user: UserProfile,
    schedules: list[DaySchedule],
    llm_configured: bool,
    llm_model: str,
) -> str:
    """Render the /settings overview screen."""
    city = html.escape(user.city_name) if user.city_name else "не выбран"
    tz = html.escape(user.timezone)
    schedule_str = html.escape(format_schedule_brief(schedules))
    comfort_str = html.escape(format_comfort_label(user.comfort_offset))

    if user.wardrobe_text:
        preview = user.wardrobe_text.strip()
        if len(preview) > 120:
            preview = preview[:117] + "..."
        wardrobe_str = html.escape(preview)
    else:
        wardrobe_str = "не заполнен (подбираю универсальные вещи)"

    if not llm_configured:
        ai_status = "не настроен ключ API (работают метео-правила)"
    elif user.use_ai:
        ai_status = f"включён ({html.escape(llm_model)})"
    else:
        ai_status = "выключен пользователем (работают метео-правила)"

    return "\n".join(
        [
            "⚙️ <b>Настройки погодного гардеробщика</b>",
            "",
            f"📍 <b>Город:</b> {city}",
            f"🕒 <b>Часовой пояс:</b> {tz}",
            f"🗓 <b>Рассылка:</b> {schedule_str}",
            (
                f"🚶 <b>Активное время:</b> "
                f"{user.active_start_hour:02d}:00–{user.active_end_hour:02d}:00"
            ),
            f"🌡 <b>Термокомфорт:</b> {comfort_str}",
            f"🧥 <b>Гардероб:</b> {wardrobe_str}",
            f"🤖 <b>ИИ-стилист:</b> {ai_status}",
        ]
    )
