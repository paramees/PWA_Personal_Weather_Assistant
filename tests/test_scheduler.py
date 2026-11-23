from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import AsyncMock

from weather_wardrobe.config import Settings
from weather_wardrobe.db.repository import Repository
from weather_wardrobe.models import HourlyWeatherPoint
from weather_wardrobe.services.ai_advisor import HybridOutfitAdvisor
from weather_wardrobe.services.scheduler import ForecastScheduler


def _hourly_series(target_date: date) -> list[HourlyWeatherPoint]:
    return [
        HourlyWeatherPoint(
            time=datetime(target_date.year, target_date.month, target_date.day, hour, 0),
            temp=10.0,
            apparent_temp=8.0,
            humidity=65,
            precip_prob=10,
            precipitation_mm=0.0,
            rain_mm=0.0,
            snowfall_cm=0.0,
            weather_code=1,
            wind_speed_ms=3.5,
            wind_gusts_ms=5.0,
            uv_index=1.0,
        )
        for hour in range(24)
    ]


async def test_scheduler_timezone_matching_and_deduplication(tmp_path: Path) -> None:
    repo = Repository(tmp_path / "sched.db")
    await repo.init()
    try:
        # User 1 in Berlin (UTC+1 in November): Monday 2026-11-23 at 07:30 == 06:30 UTC
        await repo.get_or_create_user(1)
        await repo.update_location(1, "Berlin", 52.52, 13.40, "Europe/Berlin")
        await repo.set_day_schedule(1, 0, True, "07:30")

        # User 2 in Tokyo (UTC+9): Monday 2026-11-23 at 07:30 == 2026-11-22 22:30 UTC
        await repo.get_or_create_user(2)
        await repo.update_location(2, "Tokyo", 35.67, 139.65, "Asia/Tokyo")
        await repo.set_day_schedule(2, 0, True, "07:30")

        bot = AsyncMock()
        weather_client = AsyncMock()
        weather_client.fetch_forecast = AsyncMock(
            return_value=("Europe/Berlin", _hourly_series(date(2026, 11, 23)))
        )

        import httpx

        async with httpx.AsyncClient() as http_client:
            advisor = HybridOutfitAdvisor(
                http_client,
                Settings(bot_token="123:TEST", llm_api_key=""),
            )
            scheduler = ForecastScheduler(bot, repo, weather_client, advisor)

            # 06:30 UTC -> 07:30 in Berlin, 15:30 in Tokyo -> only Berlin user receives
            sent_berlin = await scheduler.tick(datetime(2026, 11, 23, 6, 30, tzinfo=UTC))
            assert sent_berlin == 1
            assert bot.send_message.await_count == 1
            assert bot.send_message.await_args.kwargs["chat_id"] == 1

            # Second tick in the same minute must NOT double-send
            sent_dup = await scheduler.tick(datetime(2026, 11, 23, 6, 30, 40, tzinfo=UTC))
            assert sent_dup == 0
            assert bot.send_message.await_count == 1

            # 22:30 UTC on Sunday Nov 22 -> 07:30 Monday Nov 23 in Tokyo -> Tokyo user receives
            weather_client.fetch_forecast = AsyncMock(
                return_value=("Asia/Tokyo", _hourly_series(date(2026, 11, 23)))
            )
            sent_tokyo = await scheduler.tick(datetime(2026, 11, 22, 22, 30, tzinfo=UTC))
            assert sent_tokyo == 1
            assert bot.send_message.await_count == 2
            assert bot.send_message.await_args.kwargs["chat_id"] == 2
    finally:
        await repo.close()
