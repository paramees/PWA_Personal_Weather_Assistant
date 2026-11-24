from __future__ import annotations

import asyncio
import logging

import httpx
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import BotCommand

from weather_wardrobe.bot.handlers import forecast, settings, start
from weather_wardrobe.bot.middleware import AccessControlMiddleware
from weather_wardrobe.config import Settings
from weather_wardrobe.db.repository import Repository
from weather_wardrobe.services.ai_advisor import HybridOutfitAdvisor
from weather_wardrobe.services.open_meteo import OpenMeteoClient
from weather_wardrobe.services.rule_advisor import RuleBasedAdvisor
from weather_wardrobe.services.scheduler import ForecastScheduler

logger = logging.getLogger(__name__)


async def _configure_commands(bot: Bot) -> None:
    desired = [
        BotCommand(command="today", description="Погода и одежда на сегодня"),
        BotCommand(command="tomorrow", description="Погода и одежда на завтра"),
        BotCommand(command="settings", description="Город, расписание, маршрут"),
        BotCommand(command="help", description="Справка"),
    ]
    try:
        existing = await bot.get_my_commands()
        if [(c.command, c.description) for c in existing] == [
            (c.command, c.description) for c in desired
        ]:
            return
        await bot.set_my_commands(desired)
    except TelegramAPIError as exc:
        logger.warning("Skipping set_my_commands due to Telegram API error: %s", exc)


async def run_bot() -> None:
    app_settings = Settings()  # type: ignore[call-arg]
    if not app_settings.bot_token.strip():
        raise SystemExit("BOT_TOKEN is empty. Set BOT_TOKEN in .env or environment variables.")

    logging.basicConfig(
        level=getattr(logging, app_settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        force=True,
    )
    logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)

    repo = Repository(app_settings.db_path)
    await repo.init()

    http_client = httpx.AsyncClient(timeout=15.0)
    weather_client = OpenMeteoClient(http_client)
    rule_advisor = RuleBasedAdvisor()
    advisor = HybridOutfitAdvisor(http_client, app_settings, rule_advisor)

    bot = Bot(
        token=app_settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(
        repo=repo,
        weather_client=weather_client,
        advisor=advisor,
        settings=app_settings,
    )

    acl = AccessControlMiddleware(app_settings.allowed_user_ids)
    dp.message.outer_middleware(acl)
    dp.callback_query.outer_middleware(acl)

    dp.include_router(start.router)
    dp.include_router(settings.router)
    dp.include_router(forecast.router)

    scheduler = ForecastScheduler(bot, repo, weather_client, advisor)

    try:
        await _configure_commands(bot)
        scheduler.start()
        logger.info(
            "Weather Wardrobe Bot started (LLM configured=%s, models=%s).",
            app_settings.llm_configured,
            app_settings.llm_display_label,
        )
        while True:
            try:
                await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
                break
            except TelegramRetryAfter as exc:
                wait_sec = int(exc.retry_after) + 2
                logger.warning(
                    "Telegram flood limit on polling startup (%s). Sleeping %ss...",
                    exc,
                    wait_sec,
                )
                await asyncio.sleep(wait_sec)
    finally:
        scheduler.shutdown()
        await bot.session.close()
        await http_client.aclose()
        await repo.close()


def main() -> None:
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
