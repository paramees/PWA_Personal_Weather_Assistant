from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from weather_wardrobe.bot.keyboards import location_request_kb, main_reply_kb
from weather_wardrobe.bot.states import BotStates
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
            "👋 <b>Привет! Я подскажу, как одеться по погоде.</b>\n\n"
            "Напиши свой город (например: <i>Берлин</i>) или отправь геолокацию кнопкой ниже:",
            reply_markup=location_request_kb(),
        )
        return

    city = html.escape(user.city_name or "твой город")
    await message.answer(
        f"👋 <b>Привет!</b> Город: <b>{city}</b>.\n"
        "Жми <b>🌤 Сегодня</b> за прогнозом или <b>⚙️ Настройки</b>, чтобы настроить "
        "рассылку, маршрут и гардероб.",
        reply_markup=main_reply_kb(),
    )


@router.message(Command("help"), StateFilter("*"))
async def cmd_help(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "🧭 <b>Короткая справка:</b>\n\n"
        "• <b>🌤 Сегодня / 📅 Завтра</b> — погода и одежда\n"
        "• <b>⚙️ Настройки</b> — город, расписание, маршрут и гардероб\n"
        "• Любой вопрос текстом (например: <i>«в ветровке вечером не замёрзну?»</i>) "
        "— отвечу по сегодняшней погоде",
        reply_markup=main_reply_kb(),
    )


@router.message(Command("cancel"), StateFilter("*"))
@router.message(F.text == "❌ Отмена", StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_reply_kb())
