from __future__ import annotations

import html

from weather_wardrobe.models import (
    CommuteRoute,
    CommuteSummary,
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

TRANSPORT_LABELS = {
    "walk": "пешком",
    "bike": "велосипед",
    "transit": "транспорт",
    "car": "авто",
}
TRANSPORT_EMOJI = {
    "walk": "🚶",
    "bike": "🚲",
    "transit": "🚌",
    "car": "🚗",
}


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


def format_weekdays_brief(weekdays: list[int]) -> str:
    """Group sorted weekday numbers into a compact human label, e.g. 'Пн–Пт'."""
    unique = sorted({d for d in weekdays if 0 <= d <= 6})
    if not unique:
        return "не выбраны"

    groups: list[tuple[int, int]] = []
    for day in unique:
        if groups and groups[-1][1] == day - 1:
            groups[-1] = (groups[-1][0], day)
        else:
            groups.append((day, day))

    parts: list[str] = []
    for start, end in groups:
        if start == end:
            parts.append(WEEKDAY_SHORT[start])
        elif end == start + 1:
            parts.append(f"{WEEKDAY_SHORT[start]}, {WEEKDAY_SHORT[end]}")
        else:
            parts.append(f"{WEEKDAY_SHORT[start]}–{WEEKDAY_SHORT[end]}")
    return ", ".join(parts)


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
    commute: CommuteSummary | None = None,
) -> str:
    """Render a compact, mobile-first Telegram HTML card."""
    short_city = html.escape(_short_place(summary.city_name))
    weekday_name = WEEKDAY_SHORT[summary.target_date.weekday()]
    date_str = summary.target_date.strftime("%d.%m")
    tomorrow_tag = " (завтра)" if is_tomorrow else ""

    lines: list[str] = [
        f"📍 <b>{short_city}</b> · {weekday_name}, {date_str}{tomorrow_tag}",
    ]

    alerts = summary.alerts
    is_bike = bool(commute and commute.transport_mode == "bike")
    commute_rain = bool(commute and (commute.rain_on_way_there or commute.rain_on_way_back))
    alert_lines: list[str] = []

    if alerts.umbrella_required or commute_rain:
        rain_info = f" ({html.escape(alerts.rain_window)})" if alerts.rain_window else ""
        if is_bike:
            alert_lines.append(f"🌧 <b>ДОЖДЬ{rain_info}:</b> бери дождевик/мембрану")
        else:
            alert_lines.append(
                f"☔️ <b>ВОЗЬМИ ЗОНТ!</b> Дождь{rain_info} · до {summary.max_precip_prob}%"
            )
    if alerts.snow_or_ice_risk:
        alert_lines.append("❄️ <b>Снег / гололёд:</b> осторожнее на дороге")
    if alerts.big_temp_swing:
        alert_lines.append(
            f"⚠️ <b>Перепад {alerts.temp_swing_delta:g}°C:</b> одевайся слоями"
        )
    if alerts.strong_wind or (commute and commute.wind_warning):
        alert_lines.append(f"💨 <b>Сильный ветер:</b> до {summary.max_wind_ms:.0f} м/с")
    if alerts.high_uv:
        alert_lines.append(f"🕶 <b>Высокий УФ ({summary.max_uv:.0f}):</b> очки и SPF")

    if alert_lines:
        lines.append("")
        lines.extend(alert_lines)

    m, d, e = summary.morning, summary.day, summary.evening
    lines.append("")
    lines.append(
        f"🌡 Утро {_fmt_short_temp(m.temp)} ({_fmt_short_temp(m.apparent_temp)}) · "
        f"День {_fmt_short_temp(d.temp)} ({_fmt_short_temp(d.apparent_temp)}) · "
        f"Вечер {_fmt_short_temp(e.temp)} ({_fmt_short_temp(e.apparent_temp)})"
    )
    lines.append(
        f"{d.condition_emoji} {html.escape(d.condition_text)} · "
        f"💨 до {summary.max_wind_ms:.0f} м/с · 🌧 {summary.max_precip_prob}%"
    )

    if commute is not None:
        t_emoji = TRANSPORT_EMOJI[commute.transport_mode]
        t_label = TRANSPORT_LABELS[commute.transport_mode]
        dest_short = html.escape(_short_place(commute.destination_name))
        there_note = (
            f"дождь {commute.way_there.precip_prob}%" if commute.way_there.is_rain else "сухо"
        )
        back_note = (
            f"дождь {commute.way_back.precip_prob}%" if commute.way_back.is_rain else "сухо"
        )
        tmin = _fmt_short_temp(commute.at_destination_temp_min)
        tmax = _fmt_short_temp(commute.at_destination_temp_max)
        day_range = tmin if tmin == tmax else f"{tmin}…{tmax}"

        lines.append("")
        lines.append(f"{t_emoji} <b>Маршрут ({dest_short}, {t_label}):</b>")
        lines.append(
            f"• Туда ({commute.way_there.hour:02d}:00): "
            f"{_fmt_short_temp(commute.way_there.temp)} "
            f"{commute.way_there.condition_emoji}, {there_note}"
        )
        lines.append(f"• Днём там: {day_range} {commute.at_destination_condition_emoji}")
        lines.append(
            f"• Обратно ({commute.way_back.hour:02d}:00): "
            f"{_fmt_short_temp(commute.way_back.temp)} "
            f"{commute.way_back.condition_emoji}, {back_note}"
        )

    if advice.outerwear.lower().startswith(("не нуж", "днём не треб")):
        top_text = html.escape(advice.top)
    else:
        top_text = f"{html.escape(advice.outerwear)} + {html.escape(advice.top)}"

    lines.append("")
    lines.append("👕 <b>Что надеть:</b>")
    lines.append(f"• <b>Верх:</b> {top_text}")
    lines.append(
        f"• <b>Низ и обувь:</b> {html.escape(advice.bottom)}; {html.escape(advice.footwear)}"
    )
    if advice.accessories:
        acc_str = ", ".join(html.escape(item) for item in advice.accessories)
        lines.append(f"• <b>С собой:</b> {acc_str}")

    lines.append(f"💡 <i>{html.escape(advice.pro_tip)}</i>")
    return "\n".join(lines)


def _format_route_inline(route: CommuteRoute | None) -> str:
    if route is None or not route.has_destination:
        return "не настроен"
    dest = html.escape(_short_place(route.destination_name or "Точка Б"))
    t_emoji = TRANSPORT_EMOJI[route.transport_mode]
    days = format_weekdays_brief(route.weekdays)
    prefix = "" if route.enabled else "пауза · "
    return (
        f"{prefix}{days}, {route.depart_hour:02d}:00–{route.return_hour:02d}:00, "
        f"{t_emoji} → {dest}"
    )


def format_settings_summary(
    user: UserProfile,
    schedules: list[DaySchedule],
    route: CommuteRoute | None = None,
    llm_configured: bool = False,
    llm_model: str = "",
) -> str:
    """Render the compact /settings overview screen."""
    del llm_configured, llm_model
    city = html.escape(_short_place(user.city_name)) if user.city_name else "не выбран"
    schedule_str = html.escape(format_schedule_brief(schedules))
    route_str = _format_route_inline(route)

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
            f"🗓 <b>Рассылка:</b> {schedule_str}",
            f"🚶 <b>Маршрут:</b> {route_str}",
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


def format_route_summary(route: CommuteRoute) -> str:
    """Render the commute route configuration screen."""
    status = "Включён ✅" if (route.enabled and route.has_destination) else "Выключен ⚪"
    dest = (
        html.escape(route.destination_name)
        if route.destination_name
        else "не выбрана (жми «📍 Точка Б»)"
    )
    days = html.escape(format_weekdays_brief(route.weekdays))
    t_emoji = TRANSPORT_EMOJI[route.transport_mode]
    t_label = TRANSPORT_LABELS[route.transport_mode]

    return "\n".join(
        [
            "🚶 <b>Маршрут (Дом ↔ Точка Б)</b>",
            "",
            f"• Статус: <b>{status}</b>",
            f"• Точка Б: <b>{dest}</b>",
            f"• Дни: <b>{days}</b>",
            f"• Время: <b>{route.depart_hour:02d}:00 → {route.return_hour:02d}:00</b>",
            f"• Способ: <b>{t_emoji} {t_label}</b>",
        ]
    )
