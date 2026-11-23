from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from weather_wardrobe.models import DaySchedule, LocationCandidate, UserProfile
from weather_wardrobe.services.formatter import WEEKDAY_SHORT

PRESET_TIMES = ("06:30", "07:00", "07:30", "08:00", "09:00", "10:00")
COMFORT_OPTIONS = (
    (-3, "🥶 -3°C"),
    (-1, "🧥 -1°C"),
    (0, "👌 0°C"),
    (1, "🌤 +1°C"),
    (3, "🥵 +3°C"),
)
ACTIVE_HOURS_PRESETS = (
    (7, 19),
    (8, 21),
    (9, 22),
    (10, 23),
)


def main_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🌤 Сегодня"), KeyboardButton(text="📅 Завтра")],
            [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="🧥 Мой гардероб")],
        ],
        resize_keyboard=True,
    )


def location_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Отправить геолокацию", request_location=True)],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def cancel_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def forecast_inline_kb(is_tomorrow: bool) -> InlineKeyboardMarkup:
    refresh_flag = "1" if is_tomorrow else "0"
    switch_btn = (
        InlineKeyboardButton(text="🌤 На сегодня", callback_data="fc:today")
        if is_tomorrow
        else InlineKeyboardButton(text="📅 На завтра", callback_data="fc:tomorrow")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Обновить",
                    callback_data=f"fc:refresh:{refresh_flag}",
                ),
                switch_btn,
            ],
            [
                InlineKeyboardButton(text="🥶 Холоднее", callback_data="fb:cold"),
                InlineKeyboardButton(text="👍 В самый раз", callback_data="fb:ok"),
                InlineKeyboardButton(text="🥵 Жарче", callback_data="fb:hot"),
            ],
        ]
    )


def settings_main_kb(user: UserProfile, llm_configured: bool) -> InlineKeyboardMarkup:
    ai_label = "🤖 ИИ: Вкл" if (llm_configured and user.use_ai) else "🤖 ИИ: Выкл"
    if not llm_configured:
        ai_label = "🤖 ИИ: не настроен"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🗓 Расписание", callback_data="cfg:sched"),
                InlineKeyboardButton(text="📍 Город", callback_data="cfg:city"),
            ],
            [
                InlineKeyboardButton(text="🚶 Активные часы", callback_data="cfg:hours"),
                InlineKeyboardButton(text="🌡 Термокомфорт", callback_data="cfg:comfort"),
            ],
            [
                InlineKeyboardButton(text="🧥 Гардероб", callback_data="cfg:wardrobe"),
                InlineKeyboardButton(text=ai_label, callback_data="cfg:ai_toggle"),
            ],
        ]
    )


def schedule_list_kb(schedules: list[DaySchedule]) -> InlineKeyboardMarkup:
    ordered = sorted(schedules, key=lambda s: s.weekday)
    rows: list[list[InlineKeyboardButton]] = []
    current_row: list[InlineKeyboardButton] = []
    for day in ordered:
        status_icon = "✅" if day.enabled else "⚪"
        time_label = day.send_time if day.enabled else "выкл"
        btn = InlineKeyboardButton(
            text=f"{status_icon} {WEEKDAY_SHORT[day.weekday]} {time_label}",
            callback_data=f"sch:day:{day.weekday}",
        )
        current_row.append(btn)
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)

    rows.append(
        [
            InlineKeyboardButton(text="⚡ Будни 07:30", callback_data="sch:preset:wd0730"),
            InlineKeyboardButton(text="⚡ Все 08:00", callback_data="sch:preset:all0800"),
            InlineKeyboardButton(text="🔕 Выкл всё", callback_data="sch:preset:off"),
        ]
    )
    rows.append([InlineKeyboardButton(text="⬅️ Назад в настройки", callback_data="cfg:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def schedule_day_kb(day: DaySchedule) -> InlineKeyboardMarkup:
    toggle_text = "🔕 Выключить этот день" if day.enabled else "✅ Включить этот день"
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=toggle_text, callback_data=f"sch:toggle:{day.weekday}")],
    ]

    time_row: list[InlineKeyboardButton] = []
    for hhmm in PRESET_TIMES:
        compact = hhmm.replace(":", "")
        mark = "• " if day.enabled and day.send_time == hhmm else ""
        time_row.append(
            InlineKeyboardButton(
                text=f"{mark}{hhmm}",
                callback_data=f"sch:time:{day.weekday}:{compact}",
            )
        )
        if len(time_row) == 3:
            rows.append(time_row)
            time_row = []
    if time_row:
        rows.append(time_row)

    rows.append(
        [
            InlineKeyboardButton(
                text="🕒 Своё время (ЧЧ:ММ)",
                callback_data=f"sch:custom:{day.weekday}",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=f"📋 Поставить {day.send_time} всем вкл. дням",
                callback_data=f"sch:apply_all:{day.weekday}",
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="⬅️ К дням недели", callback_data="cfg:sched")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def comfort_kb(current_offset: int) -> InlineKeyboardMarkup:
    row: list[InlineKeyboardButton] = []
    for val, label in COMFORT_OPTIONS:
        prefix = "✅ " if val == current_offset else ""
        row.append(InlineKeyboardButton(text=f"{prefix}{label}", callback_data=f"cmf:set:{val}"))
    return InlineKeyboardMarkup(
        inline_keyboard=[
            row[:3],
            row[3:],
            [InlineKeyboardButton(text="⬅️ Назад в настройки", callback_data="cfg:main")],
        ]
    )


def active_hours_kb(start_hour: int, end_hour: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for s_h, e_h in ACTIVE_HOURS_PRESETS:
        mark = "✅ " if (s_h == start_hour and e_h == end_hour) else ""
        pair.append(
            InlineKeyboardButton(
                text=f"{mark}{s_h:02d}:00–{e_h:02d}:00",
                callback_data=f"hrs:set:{s_h}:{e_h}",
            )
        )
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([InlineKeyboardButton(text="🕒 Ввести свой интервал", callback_data="hrs:custom")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад в настройки", callback_data="cfg:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def city_candidates_kb(candidates: list[LocationCandidate]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, candidate in enumerate(candidates):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"📍 {candidate.display_name}",
                    callback_data=f"city:pick:{idx}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="city:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wardrobe_kb(has_wardrobe: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="✏️ Изменить гардероб", callback_data="wrd:edit")],
    ]
    if has_wardrobe:
        rows.append([InlineKeyboardButton(text="🗑 Очистить", callback_data="wrd:clear")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад в настройки", callback_data="cfg:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
