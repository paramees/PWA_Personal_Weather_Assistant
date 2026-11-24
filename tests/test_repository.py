from __future__ import annotations

from pathlib import Path

import pytest

from weather_wardrobe.db.repository import Repository


async def test_repository_user_and_schedule_crud(tmp_path: Path) -> None:
    repo = Repository(tmp_path / "bot.db")
    await repo.init()
    try:
        user = await repo.get_or_create_user(1001)
        assert user.user_id == 1001
        assert user.has_location is False

        schedules = await repo.get_schedules(1001)
        assert len(schedules) == 7
        assert all(not s.enabled and s.send_time == "08:00" for s in schedules)

        await repo.update_location(1001, "Berlin, Germany", 52.52, 13.405, "Europe/Berlin")
        await repo.update_active_hours(1001, 7, 22)
        await repo.update_wardrobe(1001, "Ветровка, пуховик")
        await repo.set_use_ai(1001, False)

        updated = await repo.get_user(1001)
        assert updated is not None
        assert updated.city_name == "Berlin, Germany"
        assert updated.timezone == "Europe/Berlin"
        assert updated.active_start_hour == 7
        assert updated.active_end_hour == 22
        assert updated.wardrobe_text == "Ветровка, пуховик"
        assert updated.use_ai is False

        with pytest.raises(ValueError):
            await repo.update_active_hours(1001, 22, 8)
    finally:
        await repo.close()


async def test_repository_presets_toggle_and_idempotent_delivery(tmp_path: Path) -> None:
    repo = Repository(tmp_path / "bot.db")
    await repo.init()
    try:
        await repo.get_or_create_user(42)
        # User without location should not appear in enabled schedules for delivery
        await repo.apply_schedule_preset(42, "weekdays_0730")
        assert await repo.get_all_enabled_schedules() == []

        await repo.update_location(42, "Moscow", 55.75, 37.61, "Europe/Moscow")
        enabled = await repo.get_all_enabled_schedules()
        assert len(enabled) == 5
        assert all(s.send_time == "07:30" and s.weekday < 5 for _, s in enabled)

        toggled = await repo.toggle_day_schedule(42, 0)
        assert toggled.enabled is False
        await repo.set_day_schedule(42, 5, True, "10:15")
        await repo.apply_time_to_enabled_days(42, "09:00")
        schedules = await repo.get_schedules(42)
        assert schedules[5].send_time == "09:00"
        assert schedules[0].enabled is False

        # Atomic idempotency check
        assert await repo.try_mark_delivered(42, "2026-11-23", "09:00") is True
        assert await repo.try_mark_delivered(42, "2026-11-23", "09:00") is False
        assert await repo.try_mark_delivered(42, "2026-11-24", "09:00") is True
    finally:
        await repo.close()


async def test_repository_feedback_and_comfort_clamping(tmp_path: Path) -> None:
    repo = Repository(tmp_path / "bot.db")
    await repo.init()
    try:
        await repo.get_or_create_user(7)
        assert await repo.adjust_comfort_offset(7, -10) == -5
        assert await repo.adjust_comfort_offset(7, 20) == 5
        assert await repo.update_comfort_offset(7, -2) == -2

        await repo.log_feedback(7, "2026-11-23", "cold", 8.5)
        await repo.log_feedback(7, "2026-11-24", "ok", 12.0)
        logs = await repo.get_recent_feedback(7, limit=5)
        assert len(logs) == 2
        assert logs[0]["feeling"] == "ok"
        assert logs[1]["feeling"] == "cold"
    finally:
        await repo.close()
