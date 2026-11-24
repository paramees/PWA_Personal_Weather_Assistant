from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from httpx import HTTPError

from weather_wardrobe.bot.keyboards import forecast_inline_kb, location_request_kb, main_reply_kb
from weather_wardrobe.bot.states import BotStates
from weather_wardrobe.config import Settings
from weather_wardrobe.db.repository import Repository
from weather_wardrobe.services.ai_advisor import HybridOutfitAdvisor
from weather_wardrobe.services.formatter import format_forecast_message
from weather_wardrobe.services.open_meteo import OpenMeteoClient
from weather_wardrobe.services.route_analyzer import compute_day_commute
from weather_wardrobe.services.weather_analyzer import analyze_day

logger = logging.getLogger(__name__)

router = Router(name="forecast")


def _safe_zoneinfo(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


async def _build_forecast_payload(
    user_id: int,
    repo: Repository,
    weather_client: OpenMeteoClient,
    advisor: HybridOutfitAdvisor,
    *,
    is_tomorrow: bool,
) -> tuple[str | None, str]:
    user = await repo.get_or_create_user(user_id)
    if not user.has_location:
        return None, "no_location"

    assert user.latitude is not None and user.longitude is not None
    tz_name, points = await weather_client.fetch_forecast(
        user.latitude,
        user.longitude,
        days=2,
    )
    effective_tz = tz_name or user.timezone
    local_now = datetime.now(_safe_zoneinfo(effective_tz))
    target_date = local_now.date() + (timedelta(days=1) if is_tomorrow else timedelta(days=0))

    summary = analyze_day(
        hourly_points=points,
        target_date=target_date,
        city_name=user.city_name or f"{user.latitude:.2f}, {user.longitude:.2f}",
        timezone=effective_tz,
        active_start_hour=user.active_start_hour,
        active_end_hour=user.active_end_hour,
    )
    route = await repo.get_route(user_id)
    commute = await compute_day_commute(weather_client, user, route, points, target_date)
    recent_feedback = await repo.get_recent_feedback(user_id, limit=5)
    advice = await advisor.advise(summary, user, recent_feedback, commute=commute)
    text = format_forecast_message(summary, advice, is_tomorrow=is_tomorrow, commute=commute)
    return text, "ok"


async def _send_forecast_message(
    message: Message,
    state: FSMContext,
    repo: Repository,
    weather_client: OpenMeteoClient,
    advisor: HybridOutfitAdvisor,
    *,
    is_tomorrow: bool,
) -> None:
    if message.from_user is None:
        return
    await state.clear()
    if message.bot is not None:
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    try:
        text, status = await _build_forecast_payload(
            message.from_user.id,
            repo,
            weather_client,
            advisor,
            is_tomorrow=is_tomorrow,
        )
    except (HTTPError, ValueError) as exc:
        logger.warning("Forecast fetch/analyze failed: %s", exc)
        await message.answer(
            "Не удалось загрузить прогноз погоды. Попробуй через минуту.",
            reply_markup=main_reply_kb(),
        )
        return

    if status == "no_location" or text is None:
        await state.set_state(BotStates.waiting_city)
        await message.answer(
            "📍 Сначала укажи свой город — напиши название или отправь геолокацию:",
            reply_markup=location_request_kb(),
        )
        return

    await message.answer(text, reply_markup=forecast_inline_kb(is_tomorrow=is_tomorrow))


@router.message(Command("today"), StateFilter("*"))
@router.message(F.text == "🌤 Сегодня", StateFilter("*"))
async def cmd_today(
    message: Message,
    state: FSMContext,
    repo: Repository,
    weather_client: OpenMeteoClient,
    advisor: HybridOutfitAdvisor,
) -> None:
    await _send_forecast_message(
        message,
        state,
        repo,
        weather_client,
        advisor,
        is_tomorrow=False,
    )


@router.message(Command("tomorrow"), StateFilter("*"))
@router.message(F.text == "📅 Завтра", StateFilter("*"))
async def cmd_tomorrow(
    message: Message,
    state: FSMContext,
    repo: Repository,
    weather_client: OpenMeteoClient,
    advisor: HybridOutfitAdvisor,
) -> None:
    await _send_forecast_message(
        message,
        state,
        repo,
        weather_client,
        advisor,
        is_tomorrow=True,
    )


@router.callback_query(F.data.in_({"fc:today", "fc:tomorrow", "fc:refresh:0", "fc:refresh:1"}))
async def cb_forecast_switch_or_refresh(
    callback: CallbackQuery,
    repo: Repository,
    weather_client: OpenMeteoClient,
    advisor: HybridOutfitAdvisor,
) -> None:
    if not isinstance(callback.message, Message) or not callback.data:
        await callback.answer()
        return

    is_tomorrow = callback.data in {"fc:tomorrow", "fc:refresh:1"}
    try:
        text, status = await _build_forecast_payload(
            callback.from_user.id,
            repo,
            weather_client,
            advisor,
            is_tomorrow=is_tomorrow,
        )
    except (HTTPError, ValueError) as exc:
        logger.warning("Forecast callback refresh failed: %s", exc)
        await callback.answer("Ошибка загрузки прогноза 😔", show_alert=True)
        return

    if status == "no_location" or text is None:
        await callback.answer("Сначала выбери город в /settings", show_alert=True)
        return

    try:
        await callback.message.edit_text(
            text,
            reply_markup=forecast_inline_kb(is_tomorrow=is_tomorrow),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            logger.warning("Could not edit forecast message: %s", exc)
    await callback.answer("Обновлено 🔄" if callback.data.startswith("fc:refresh") else None)


@router.callback_query(F.data.in_({"fb:cold", "fb:ok", "fb:hot"}))
async def cb_feedback(callback: CallbackQuery, repo: Repository) -> None:
    if not callback.data:
        await callback.answer()
        return
    feeling = callback.data.split(":")[1]
    user = await repo.get_or_create_user(callback.from_user.id)
    local_date = datetime.now(_safe_zoneinfo(user.timezone)).date().isoformat()

    if feeling == "cold":
        await repo.log_feedback(user.user_id, local_date, "cold")
        new_offset = await repo.adjust_comfort_offset(user.user_id, -1)
        await callback.answer(
            f"Учтено! Термопорог: {new_offset:+d}°C — буду советовать одеваться теплее 🧥",
            show_alert=True,
        )
    elif feeling == "hot":
        await repo.log_feedback(user.user_id, local_date, "hot")
        new_offset = await repo.adjust_comfort_offset(user.user_id, 1)
        await callback.answer(
            f"Учтено! Термопорог: {new_offset:+d}°C — буду советовать одеваться легче 👕",
            show_alert=True,
        )
    else:
        await repo.log_feedback(user.user_id, local_date, "ok")
        await callback.answer("Отлично, зафиксировал! 👍")


@router.message(StateFilter(None), F.text)
async def handle_free_text_qa(
    message: Message,
    repo: Repository,
    weather_client: OpenMeteoClient,
    advisor: HybridOutfitAdvisor,
    settings: Settings,
) -> None:
    """Catch-all free-text handler for natural-language weather/outfit follow-up questions."""
    if message.from_user is None or not message.text:
        return
    question = message.text.strip()
    if not question or question.startswith("/"):
        return

    user = await repo.get_or_create_user(message.from_user.id)
    if not user.has_location:
        await message.answer(
            "📍 Сначала укажи город через /start или <b>⚙️ Настройки</b>, чтобы я знал погоду.",
            reply_markup=main_reply_kb(),
        )
        return

    if not settings.llm_configured or not user.use_ai:
        await message.answer(
            "🤖 Ответы на свободные вопросы работают при включённом ИИ-стилисте "
            "(нужен <code>LLM_API_KEY</code> в <code>.env</code>).\n\n"
            "Пока можешь посмотреть прогноз по кнопкам <b>🌤 Сегодня</b> или <b>📅 Завтра</b>.",
            reply_markup=main_reply_kb(),
        )
        return

    if message.bot is not None:
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    try:
        assert user.latitude is not None and user.longitude is not None
        tz_name, points = await weather_client.fetch_forecast(
            user.latitude,
            user.longitude,
            days=2,
        )
        effective_tz = tz_name or user.timezone
        local_date = datetime.now(_safe_zoneinfo(effective_tz)).date()
        summary = analyze_day(
            hourly_points=points,
            target_date=local_date,
            city_name=user.city_name or f"{user.latitude:.2f}, {user.longitude:.2f}",
            timezone=effective_tz,
            active_start_hour=user.active_start_hour,
            active_end_hour=user.active_end_hour,
        )
        route = await repo.get_route(user.user_id)
        commute = await compute_day_commute(weather_client, user, route, points, local_date)
    except (HTTPError, ValueError) as exc:
        logger.warning("Q&A forecast fetch failed: %s", exc)
        await message.answer(
            "Не получилось получить актуальную погоду для ответа. Попробуй позже.",
            reply_markup=main_reply_kb(),
        )
        return

    answer = await advisor.answer_question(question, summary, user, commute=commute)
    if answer is None:
        await message.answer(
            "ИИ-сервис временно не отвечает 😔 Но ты всегда можешь открыть <b>🌤 Сегодня</b>.",
            reply_markup=main_reply_kb(),
        )
        return

    await message.answer(f"🤖 {html.escape(answer)}", reply_markup=main_reply_kb())
