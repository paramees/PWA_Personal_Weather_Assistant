from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from weather_wardrobe.bot.keyboards import location_request_kb, main_reply_kb
from weather_wardrobe.bot.states import BotStates
from weather_wardrobe.config import Settings
from weather_wardrobe.db.repository import Repository

router = Router(name="start")


@router.message(CommandStart(), StateFilter("*"))
async def cmd_start(
    message: Message,
    state: FSMContext,
    repo: Repository,
) -> None:
    if message.from_user is None:
        return
    await state.clear()
    user = await repo.get_or_create_user(message.from_user.id)

    if not user.has_location:
        await state.set_state(BotStates.waiting_city)
        await message.answer(
            "👋 <b>Привет! Я твой погодный гардеробщик.</b>\n\n"
            "Каждое выбранное утро я проверяю прогноз, предупреждаю о дожде/ветре "
            "и подсказываю, что именно надеть (в том числе из твоего реального гардероба).\n\n"
            "Для начала укажи свой город — <b>напиши название</b> (например: <i>Берлин</i> "
            "или <i>Москва</i>) либо нажми кнопку ниже и отправь геолокацию:",
            reply_markup=location_request_kb(),
        )
        return

    city = html.escape(user.city_name or "твой город")
    await message.answer(
        f"👋 <b>С возвращением!</b>\n\n"
        f"Текущий город: <b>{city}</b>.\n"
        "Жми <b>🌤 Сегодня</b> для прогноза и подбора одежды или <b>⚙️ Настройки</b>, "
        "чтобы настроить расписание по дням недели и свой гардероб.",
        reply_markup=main_reply_kb(),
    )


@router.message(Command("help"), StateFilter("*"))
async def cmd_help(
    message: Message,
    state: FSMContext,
    settings: Settings,
) -> None:
    await state.clear()
    ai_note = (
        "• <b>Свободный вопрос текстом</b> (например: <i>«пойду вечером пешком, "
        "замерзну в ветровке?»</i>) — отвечу с учётом сегодняшней погоды и твоего гардероба."
        if settings.llm_configured
        else "• <i>ИИ-стилист сейчас не подключён (работают надёжные метео-правила). "
        "Добавь LLM_API_KEY в .env для умного подбора из своего шкафа и ответов на вопросы.</i>"
    )
    await message.answer(
        "🧭 <b>Что я умею:</b>\n\n"
        "• /today или <b>🌤 Сегодня</b> — прогноз по слотам, алерты и рекомендации по одежде.\n"
        "• /tomorrow или <b>📅 Завтра</b> — то же самое на завтра.\n"
        "• /settings или <b>⚙️ Настройки</b> — город, расписание на каждый день недели, "
        "активные часы и уровень мерзлявости.\n"
        "• /wardrobe или <b>🧥 Мой гардероб</b> — список твоих реальных курток и обуви.\n"
        f"{ai_note}",
        reply_markup=main_reply_kb(),
    )


@router.message(Command("cancel"), StateFilter("*"))
@router.message(F.text == "❌ Отмена", StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_reply_kb())
