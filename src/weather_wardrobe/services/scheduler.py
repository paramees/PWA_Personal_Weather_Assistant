from __future__ import annotations

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from weather_wardrobe.bot.keyboards import forecast_inline_kb
from weather_wardrobe.db.repository import Repository
from weather_wardrobe.services.ai_advisor import HybridOutfitAdvisor
from weather_wardrobe.services.formatter import format_forecast_message
from weather_wardrobe.services.open_meteo import OpenMeteoClient
from weather_wardrobe.services.weather_analyzer import analyze_day

logger = logging.getLogger(__name__)


class ForecastScheduler:
    """Timezone-aware minute-precision scheduler for personalized morning forecasts."""

    def __init__(
        self,
        bot: Bot,
        repo: Repository,
        weather_client: OpenMeteoClient,
        advisor: HybridOutfitAdvisor,
    ) -> None:
        self.bot = bot
        self.repo = repo
        self.weather_client = weather_client
        self.advisor = advisor
        self._scheduler = AsyncIOScheduler(timezone=UTC)

    def start(self) -> None:
        self._scheduler.add_job(
            self.tick,
            trigger=CronTrigger(second=5),
            id="forecast_tick",
            replace_existing=True,
            misfire_grace_time=30,
        )
        self._scheduler.start()
        logger.info("ForecastScheduler started (checking schedules every minute at :05s).")

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("ForecastScheduler stopped.")

    async def tick(self, now_utc: datetime | None = None) -> int:
        """Check all enabled schedules against current UTC time and send due forecasts."""
        current_utc = now_utc or datetime.now(UTC)
        if current_utc.tzinfo is None:
            current_utc = current_utc.replace(tzinfo=UTC)

        entries = await self.repo.get_all_enabled_schedules()
        sent_count = 0

        for user, schedule in entries:
            try:
                try:
                    user_tz = ZoneInfo(user.timezone)
                except ZoneInfoNotFoundError:
                    user_tz = UTC

                local_now = current_utc.astimezone(user_tz)
                if local_now.weekday() != schedule.weekday:
                    continue
                if local_now.strftime("%H:%M") != schedule.send_time:
                    continue

                local_date_str = local_now.date().isoformat()
                should_deliver = await self.repo.try_mark_delivered(
                    user.user_id,
                    local_date_str,
                    schedule.send_time,
                )
                if not should_deliver:
                    continue

                assert user.latitude is not None and user.longitude is not None
                tz_name, points = await self.weather_client.fetch_forecast(
                    user.latitude,
                    user.longitude,
                    days=2,
                )
                summary = analyze_day(
                    hourly_points=points,
                    target_date=local_now.date(),
                    city_name=user.city_name or f"{user.latitude:.2f}, {user.longitude:.2f}",
                    timezone=tz_name or user.timezone,
                    active_start_hour=user.active_start_hour,
                    active_end_hour=user.active_end_hour,
                )
                recent_feedback = await self.repo.get_recent_feedback(user.user_id, limit=5)
                advice = await self.advisor.advise(summary, user, recent_feedback)
                text = format_forecast_message(summary, advice, is_tomorrow=False)

                await self.bot.send_message(
                    chat_id=user.user_id,
                    text=text,
                    reply_markup=forecast_inline_kb(is_tomorrow=False),
                )
                sent_count += 1
                logger.info(
                    "Sent scheduled forecast to user=%s at %s (%s)",
                    user.user_id,
                    schedule.send_time,
                    user.timezone,
                )
            except Exception:
                logger.exception("Failed scheduled delivery for user=%s", user.user_id)

        return sent_count
