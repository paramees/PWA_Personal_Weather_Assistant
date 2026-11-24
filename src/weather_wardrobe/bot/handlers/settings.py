from __future__ import annotations

import html
import logging
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from httpx import HTTPError

from weather_wardrobe.bot.keyboards import (
    active_hours_kb,
    cancel_reply_kb,
    city_candidates_kb,
    comfort_kb,
    location_request_kb,
    main_reply_kb,
    onboarding_schedule_kb,
    schedule_day_kb,
    schedule_list_kb,
    settings_advanced_kb,
    settings_main_kb,
    wardrobe_kb,
)
from weather_wardrobe.bot.states import BotStates
from weather_wardrobe.config import Settings
from weather_wardrobe.db.repository import Repository
from weather_wardrobe.models import LocationCandidate
from weather_wardrobe.services.formatter import (
    WEEKDAY_FULL,
    format_advanced_settings_summary,
    format_comfort_label,
    format_schedule_brief,
    format_settings_summary,
)
from weather_wardrobe.services.open_meteo import OpenMeteoClient

logger = logging.getLogger(__name__)

router = Router(name="settings")

_TIME_RE = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*$")
_HOURS_RE = re.compile(r"^\s*(\d{1,2})(?::\d{2})?\s*[-–—]\s*(\d{1,2})(?::\d{2})?\s*$")


async def _safe_edit(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            logger.warning("Failed to edit message: %s", exc)


async def _build_settings_view(
    repo: Repository,
    settings: Settings,
    user_id: int,
) -> tuple[str, InlineKeyboardMarkup]:
    user = await repo.get_or_create_user(user_id)
    schedules = await repo.get_schedules(user_id)
    text = format_settings_summary(
        user=user,
        schedules=schedules,
        llm_configured=settings.llm_configured,
        llm_model=settings.llm_display_label,
    )
    kb = settings_main_kb(user, settings.llm_configured)
    return text, kb


async def _maybe_prompt_schedule(
    message: Message,
    repo: Repository,
    user_id: int,
) -> None:
    """Offer quick morning schedule activation right after onboarding city setup."""
    schedules = await repo.get_schedules(user_id)
    if any(day.enabled for day in schedules):
        return
    await message.answer(
        "🗓 <b>Утренняя рассылка пока выключена.</b>\n"
        "Включи её в один клик или настрой удобное время для каждого дня:",
        reply_markup=onboarding_schedule_kb(),
    )


async def _build_advanced_view(
    repo: Repository,
    settings: Settings,
    user_id: int,
) -> tuple[str, InlineKeyboardMarkup]:
    user = await repo.get_or_create_user(user_id)
    text = format_advanced_settings_summary(
        user=user,
        llm_configured=settings.llm_configured,
        llm_model=settings.llm_display_label,
    )
    kb = settings_advanced_kb(user, settings.llm_configured)
    return text, kb


def _render_wardrobe_text(wardrobe_text: str) -> str:
    if wardrobe_text.strip():
        escaped = html.escape(wardrobe_text.strip())
        body = f"<b>Сейчас в твоём списке:</b>\n<blockquote>{escaped}</blockquote>"
    else:
        body = (
            "Пока список пуст. Добавь свои реальные куртки, обувь и головные уборы, "
            "чтобы ИИ советовал конкретно вещи из твоего шкафа."
        )
    return (
        "🧥 <b>Мой гардероб</b>\n\n"
        f"{body}\n\n"
        "<i>Пример: «Тонкая ветровка, чёрное пальто, тёплый пуховик, "
        "кожаные кроссовки, замшевые ботинки, худи».</i>"
    )


def _render_day_text(weekday: int, enabled: bool, send_time: str) -> str:
    status = "Включена ✅" if enabled else "Выключена ⚪"
    return (
        f"🗓 <b>{WEEKDAY_FULL[weekday]}</b>\n\n"
        f"• Статус: <b>{status}</b>\n"
        f"• Время отправки: <b>{send_time}</b>\n\n"
        "Выбери готовое время или введи своё в формате <code>ЧЧ:ММ</code>:"
    )


@router.message(Command("settings"), StateFilter("*"))
@router.message(F.text == "⚙️ Настройки", StateFilter("*"))
async def cmd_settings(
    message: Message,
    state: FSMContext,
    repo: Repository,
    settings: Settings,
) -> None:
    if message.from_user is None:
        return
    await state.clear()
    text, kb = await _build_settings_view(repo, settings, message.from_user.id)
    await message.answer(text, reply_markup=kb)


@router.message(Command("wardrobe"), StateFilter("*"))
@router.message(F.text == "🧥 Мой гардероб", StateFilter("*"))
async def cmd_wardrobe(
    message: Message,
    state: FSMContext,
    repo: Repository,
) -> None:
    if message.from_user is None:
        return
    await state.clear()
    user = await repo.get_or_create_user(message.from_user.id)
    await message.answer(
        _render_wardrobe_text(user.wardrobe_text),
        reply_markup=wardrobe_kb(bool(user.wardrobe_text)),
    )


@router.callback_query(F.data == "cfg:main")
async def cb_settings_main(
    callback: CallbackQuery,
    repo: Repository,
    settings: Settings,
) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    text, kb = await _build_settings_view(repo, settings, callback.from_user.id)
    await _safe_edit(callback.message, text, kb)
    await callback.answer()


@router.callback_query(F.data == "cfg:more")
async def cb_settings_more(
    callback: CallbackQuery,
    repo: Repository,
    settings: Settings,
) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    text, kb = await _build_advanced_view(repo, settings, callback.from_user.id)
    await _safe_edit(callback.message, text, kb)
    await callback.answer()


@router.callback_query(F.data == "cfg:sched")
async def cb_settings_schedule(callback: CallbackQuery, repo: Repository) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    schedules = await repo.get_schedules(callback.from_user.id)
    brief = html.escape(format_schedule_brief(schedules))
    await _safe_edit(
        callback.message,
        "🗓 <b>Расписание утренней рассылки</b>\n\n"
        f"Текущий график: <b>{brief}</b>\n\n"
        "Нажми на любой день недели, чтобы включить/выключить его или задать точное время:",
        schedule_list_kb(schedules),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sch:day:"))
async def cb_schedule_day(callback: CallbackQuery, repo: Repository) -> None:
    if not isinstance(callback.message, Message) or not callback.data:
        await callback.answer()
        return
    weekday = int(callback.data.split(":")[2])
    schedules = await repo.get_schedules(callback.from_user.id)
    day = schedules[weekday]
    await _safe_edit(
        callback.message,
        _render_day_text(day.weekday, day.enabled, day.send_time),
        schedule_day_kb(day),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sch:toggle:"))
async def cb_schedule_toggle(callback: CallbackQuery, repo: Repository) -> None:
    if not isinstance(callback.message, Message) or not callback.data:
        await callback.answer()
        return
    weekday = int(callback.data.split(":")[2])
    day = await repo.toggle_day_schedule(callback.from_user.id, weekday)
    await _safe_edit(
        callback.message,
        _render_day_text(day.weekday, day.enabled, day.send_time),
        schedule_day_kb(day),
    )
    await callback.answer("Включено ✅" if day.enabled else "Выключено ⚪")


@router.callback_query(F.data.startswith("sch:time:"))
async def cb_schedule_time_preset(callback: CallbackQuery, repo: Repository) -> None:
    if not isinstance(callback.message, Message) or not callback.data:
        await callback.answer()
        return
    _, _, weekday_str, compact = callback.data.split(":")
    weekday = int(weekday_str)
    formatted = f"{compact[:2]}:{compact[2:]}"
    await repo.set_day_schedule(
        callback.from_user.id,
        weekday,
        enabled=True,
        send_time=formatted,
    )
    schedules = await repo.get_schedules(callback.from_user.id)
    day = schedules[weekday]
    await _safe_edit(
        callback.message,
        _render_day_text(day.weekday, day.enabled, day.send_time),
        schedule_day_kb(day),
    )
    await callback.answer(f"Установлено {formatted} ✅")


@router.callback_query(F.data.startswith("sch:custom:"))
async def cb_schedule_custom_time(callback: CallbackQuery, state: FSMContext) -> None:
    if not isinstance(callback.message, Message) or not callback.data:
        await callback.answer()
        return
    weekday = int(callback.data.split(":")[2])
    await state.set_state(BotStates.waiting_custom_time)
    await state.update_data(editing_weekday=weekday)
    await callback.message.answer(
        f"🕒 Введи время для <b>{WEEKDAY_FULL[weekday]}</b> в формате <code>ЧЧ:ММ</code> "
        "(например: <code>07:15</code> или <code>8:40</code>):",
        reply_markup=cancel_reply_kb(),
    )
    await callback.answer()


@router.message(BotStates.waiting_custom_time, F.text)
async def handle_custom_time_input(
    message: Message,
    state: FSMContext,
    repo: Repository,
) -> None:
    if message.from_user is None or not message.text:
        return
    match = _TIME_RE.fullmatch(message.text)
    if not match:
        await message.answer(
            "Неверный формат. Введи время как <code>07:30</code> или <code>8:15</code>."
        )
        return
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        await message.answer("Часы должны быть от 00 до 23, а минуты от 00 до 59.")
        return

    normalized = f"{hour:02d}:{minute:02d}"
    data = await state.get_data()
    weekday = int(data.get("editing_weekday", 0))
    await repo.set_day_schedule(
        message.from_user.id,
        weekday,
        enabled=True,
        send_time=normalized,
    )
    await state.clear()
    schedules = await repo.get_schedules(message.from_user.id)
    day = schedules[weekday]

    await message.answer(
        f"✅ Для <b>{WEEKDAY_FULL[weekday]}</b> установлено время <b>{normalized}</b>.",
        reply_markup=main_reply_kb(),
    )
    await message.answer(
        _render_day_text(day.weekday, day.enabled, day.send_time),
        reply_markup=schedule_day_kb(day),
    )


@router.callback_query(F.data.startswith("sch:apply_all:"))
async def cb_schedule_apply_all(callback: CallbackQuery, repo: Repository) -> None:
    if not isinstance(callback.message, Message) or not callback.data:
        await callback.answer()
        return
    weekday = int(callback.data.split(":")[2])
    schedules = await repo.get_schedules(callback.from_user.id)
    target_time = schedules[weekday].send_time
    await repo.apply_time_to_enabled_days(callback.from_user.id, target_time)
    updated = await repo.get_schedules(callback.from_user.id)
    brief = html.escape(format_schedule_brief(updated))
    await _safe_edit(
        callback.message,
        "🗓 <b>Расписание утренней рассылки</b>\n\n"
        f"Текущий график: <b>{brief}</b>\n\n"
        "Нажми на любой день недели, чтобы включить/выключить его или задать точное время:",
        schedule_list_kb(updated),
    )
    await callback.answer(f"Время {target_time} применено ко всем включённым дням!")


@router.callback_query(F.data.startswith("sch:preset:"))
async def cb_schedule_preset(callback: CallbackQuery, repo: Repository) -> None:
    if not isinstance(callback.message, Message) or not callback.data:
        await callback.answer()
        return
    code = callback.data.split(":")[2]
    if code == "wd0730":
        await repo.apply_schedule_preset(callback.from_user.id, "weekdays_0730")
        toast = "Пн–Пт 07:30 ✅"
    elif code == "all0800":
        await repo.apply_schedule_preset(callback.from_user.id, "all_0800")
        toast = "Все дни 08:00 ✅"
    else:
        await repo.apply_schedule_preset(callback.from_user.id, "off_all")
        toast = "Рассылка выключена 🔕"

    schedules = await repo.get_schedules(callback.from_user.id)
    brief = html.escape(format_schedule_brief(schedules))
    await _safe_edit(
        callback.message,
        "🗓 <b>Расписание утренней рассылки</b>\n\n"
        f"Текущий график: <b>{brief}</b>\n\n"
        "Нажми на любой день недели, чтобы включить/выключить его или задать точное время:",
        schedule_list_kb(schedules),
    )
    await callback.answer(toast)


@router.callback_query(F.data == "cfg:city")
async def cb_settings_city(callback: CallbackQuery, state: FSMContext) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    await state.set_state(BotStates.waiting_city)
    await callback.message.answer(
        "📍 Напиши название города (например: <i>Прага</i> или <i>Санкт-Петербург</i>) "
        "либо отправь геолокацию кнопкой ниже:",
        reply_markup=location_request_kb(),
    )
    await callback.answer()


@router.message(F.location, StateFilter("*"))
async def handle_location_pin(
    message: Message,
    state: FSMContext,
    repo: Repository,
    weather_client: OpenMeteoClient,
) -> None:
    if message.from_user is None or message.location is None:
        return
    lat = message.location.latitude
    lon = message.location.longitude
    await state.clear()

    city_name = await weather_client.reverse_geocode_city(lat, lon)
    try:
        tz_name, _ = await weather_client.fetch_forecast(lat, lon, days=1)
    except HTTPError:
        tz_name = "UTC"

    await repo.update_location(message.from_user.id, city_name, lat, lon, tz_name)
    await message.answer(
        f"✅ Город сохранён: <b>{html.escape(city_name)}</b>.\n"
        "Жми <b>🌤 Сегодня</b> за прогнозом или <b>⚙️ Настройки</b>.",
        reply_markup=main_reply_kb(),
    )
    await _maybe_prompt_schedule(message, repo, message.from_user.id)


@router.message(BotStates.waiting_city, F.text)
async def handle_city_text(
    message: Message,
    state: FSMContext,
    weather_client: OpenMeteoClient,
) -> None:
    if not message.text:
        return
    try:
        candidates = await weather_client.search_cities(message.text, count=5)
    except HTTPError:
        await message.answer(
            "Не получилось связаться с сервисом геокодинга. Попробуй ещё раз через минуту."
        )
        return

    if not candidates:
        await message.answer(
            "Не нашёл такой город 😔 Попробуй написать иначе (например, на английском) "
            "или отправь геолокацию кнопкой."
        )
        return

    await state.update_data(city_candidates=[c.model_dump() for c in candidates])
    await message.answer(
        "Выбери подходящий вариант:",
        reply_markup=city_candidates_kb(candidates),
    )


@router.callback_query(F.data.startswith("city:pick:"))
async def cb_city_pick(
    callback: CallbackQuery,
    state: FSMContext,
    repo: Repository,
) -> None:
    if not isinstance(callback.message, Message) or not callback.data:
        await callback.answer()
        return
    data = await state.get_data()
    raw_candidates = data.get("city_candidates") or []
    idx = int(callback.data.split(":")[2])
    if idx < 0 or idx >= len(raw_candidates):
        await callback.answer("Список устарел, введи город заново.", show_alert=True)
        await state.clear()
        return

    chosen = LocationCandidate.model_validate(raw_candidates[idx])
    await repo.update_location(
        callback.from_user.id,
        chosen.display_name,
        chosen.latitude,
        chosen.longitude,
        chosen.timezone,
    )
    await state.clear()
    await _safe_edit(
        callback.message,
        f"✅ Город сохранён: <b>{html.escape(chosen.display_name)}</b>.",
    )
    await callback.message.answer(
        "Жми <b>🌤 Сегодня</b> за прогнозом или <b>⚙️ Настройки</b>.",
        reply_markup=main_reply_kb(),
    )
    await _maybe_prompt_schedule(callback.message, repo, callback.from_user.id)
    await callback.answer("Город сохранён 📍")


@router.callback_query(F.data == "city:cancel")
async def cb_city_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if isinstance(callback.message, Message):
        await _safe_edit(callback.message, "Выбор города отменён.")
        await callback.message.answer("Главное меню:", reply_markup=main_reply_kb())
    await callback.answer()


@router.callback_query(F.data == "cfg:comfort")
async def cb_settings_comfort(callback: CallbackQuery, repo: Repository) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    user = await repo.get_or_create_user(callback.from_user.id)
    label = html.escape(format_comfort_label(user.comfort_offset))
    await _safe_edit(
        callback.message,
        "🌡 <b>Настройка термокомфорта</b>\n\n"
        f"Текущая поправка: <b>{label}</b>\n\n"
        "• Отрицательное значение (<code>-1</code>, <code>-3</code>) — если быстро мёрзнешь "
        "(буду советовать одеваться теплее).\n"
        "• Положительное (<code>+1</code>, <code>+3</code>) — если тебе обычно жарко.",
        comfort_kb(user.comfort_offset),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cmf:set:"))
async def cb_comfort_set(callback: CallbackQuery, repo: Repository) -> None:
    if not isinstance(callback.message, Message) or not callback.data:
        await callback.answer()
        return
    val = int(callback.data.split(":")[2])
    updated = await repo.update_comfort_offset(callback.from_user.id, val)
    label = html.escape(format_comfort_label(updated))
    await _safe_edit(
        callback.message,
        "🌡 <b>Настройка термокомфорта</b>\n\n"
        f"Текущая поправка: <b>{label}</b>\n\n"
        "• Отрицательное значение (<code>-1</code>, <code>-3</code>) — если быстро мёрзнешь "
        "(буду советовать одеваться теплее).\n"
        "• Положительное (<code>+1</code>, <code>+3</code>) — если тебе обычно жарко.",
        comfort_kb(updated),
    )
    await callback.answer(f"Установлено: {updated:+d}°C")


@router.callback_query(F.data == "cfg:hours")
async def cb_settings_hours(callback: CallbackQuery, repo: Repository) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    user = await repo.get_or_create_user(callback.from_user.id)
    await _safe_edit(
        callback.message,
        "🚶 <b>Активное время вне дома</b>\n\n"
        f"Сейчас анализирую погоду с <b>{user.active_start_hour:02d}:00</b> "
        f"до <b>{user.active_end_hour:02d}:00</b>, чтобы ночной холод не искажал советы.\n\n"
        "Выбери удобный интервал:",
        active_hours_kb(user.active_start_hour, user.active_end_hour),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("hrs:set:"))
async def cb_hours_set(callback: CallbackQuery, repo: Repository) -> None:
    if not isinstance(callback.message, Message) or not callback.data:
        await callback.answer()
        return
    _, _, start_str, end_str = callback.data.split(":")
    start_h, end_h = int(start_str), int(end_str)
    await repo.update_active_hours(callback.from_user.id, start_h, end_h)
    await _safe_edit(
        callback.message,
        "🚶 <b>Активное время вне дома</b>\n\n"
        f"Сейчас анализирую погоду с <b>{start_h:02d}:00</b> до <b>{end_h:02d}:00</b>.\n\n"
        "Выбери удобный интервал:",
        active_hours_kb(start_h, end_h),
    )
    await callback.answer(f"Интервал {start_h:02d}:00–{end_h:02d}:00 ✅")


@router.callback_query(F.data == "hrs:custom")
async def cb_hours_custom(callback: CallbackQuery, state: FSMContext) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    await state.set_state(BotStates.waiting_active_hours)
    await callback.message.answer(
        "🕒 Введи часы начала и конца дня через дефис (например: <code>8-21</code> или "
        "<code>07:00-22:00</code>):",
        reply_markup=cancel_reply_kb(),
    )
    await callback.answer()


@router.message(BotStates.waiting_active_hours, F.text)
async def handle_active_hours_input(
    message: Message,
    state: FSMContext,
    repo: Repository,
) -> None:
    if message.from_user is None or not message.text:
        return
    match = _HOURS_RE.fullmatch(message.text)
    if not match:
        await message.answer(
            "Формат не распознан. Пример: <code>8-21</code> или <code>9-22</code>."
        )
        return
    start_h, end_h = int(match.group(1)), int(match.group(2))
    if not (0 <= start_h < end_h <= 23):
        await message.answer(
            "Начало должно быть меньше конца, и оба часа в диапазоне от 0 до 23 "
            "(например: <code>8-21</code>)."
        )
        return

    await repo.update_active_hours(message.from_user.id, start_h, end_h)
    await state.clear()
    await message.answer(
        f"✅ Активное окно обновлено: <b>{start_h:02d}:00–{end_h:02d}:00</b>.",
        reply_markup=main_reply_kb(),
    )


@router.callback_query(F.data == "cfg:wardrobe")
async def cb_settings_wardrobe(callback: CallbackQuery, repo: Repository) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    user = await repo.get_or_create_user(callback.from_user.id)
    await _safe_edit(
        callback.message,
        _render_wardrobe_text(user.wardrobe_text),
        wardrobe_kb(bool(user.wardrobe_text)),
    )
    await callback.answer()


@router.callback_query(F.data == "wrd:edit")
async def cb_wardrobe_edit(callback: CallbackQuery, state: FSMContext) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    await state.set_state(BotStates.waiting_wardrobe)
    await callback.message.answer(
        "🧥 Отправь одним сообщением список своей верхней одежды, обуви и тёплых вещей.\n\n"
        "<i>Например: «Тонкая чёрная ветровка, бежевый тренч, зимний пуховик, "
        "кожаные белые кеды, замшевые челси, толстовка, джинсы».</i>",
        reply_markup=cancel_reply_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "wrd:clear")
async def cb_wardrobe_clear(callback: CallbackQuery, repo: Repository) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    await repo.update_wardrobe(callback.from_user.id, "")
    await _safe_edit(
        callback.message,
        _render_wardrobe_text(""),
        wardrobe_kb(False),
    )
    await callback.answer("Гардероб очищен")


@router.message(BotStates.waiting_wardrobe, F.text)
async def handle_wardrobe_input(
    message: Message,
    state: FSMContext,
    repo: Repository,
) -> None:
    if message.from_user is None or not message.text:
        return
    cleaned = message.text.strip()
    if len(cleaned) > 1500:
        await message.answer(
            "Список слишком длинный (больше 1500 символов). Опиши чуть короче основные вещи."
        )
        return
    await repo.update_wardrobe(message.from_user.id, cleaned)
    await state.clear()
    await message.answer(
        "✅ Гардероб обновлён! ИИ-стилист будет учитывать эти вещи при подборе.",
        reply_markup=main_reply_kb(),
    )
    await message.answer(
        _render_wardrobe_text(cleaned),
        reply_markup=wardrobe_kb(True),
    )


@router.callback_query(F.data == "cfg:ai_toggle")
async def cb_ai_toggle(
    callback: CallbackQuery,
    repo: Repository,
    settings: Settings,
) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    if not settings.llm_configured:
        await callback.answer(
            "LLM_API_KEY не задан в .env — сейчас работают метео-правила.",
            show_alert=True,
        )
        return
    user = await repo.get_or_create_user(callback.from_user.id)
    new_val = not user.use_ai
    await repo.set_use_ai(callback.from_user.id, new_val)
    text, kb = await _build_advanced_view(repo, settings, callback.from_user.id)
    await _safe_edit(callback.message, text, kb)
    await callback.answer("ИИ-стилист включён 🤖" if new_val else "ИИ-стилист выключен 📐")
