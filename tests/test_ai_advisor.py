from __future__ import annotations

import json
from datetime import date

import httpx

from weather_wardrobe.config import Settings
from weather_wardrobe.models import (
    CommuteLegSummary,
    CommuteSummary,
    DayWeatherSummary,
    SlotSummary,
    UserProfile,
    WeatherAlerts,
)
from weather_wardrobe.services.ai_advisor import HybridOutfitAdvisor


def _make_summary(*, umbrella: bool = False, rain_window: str | None = None) -> DayWeatherSummary:
    slot = SlotSummary(
        label="День",
        hour=14,
        temp=11.0,
        apparent_temp=9.0,
        weather_code=61 if umbrella else 2,
        condition_text="Небольшой дождь" if umbrella else "Переменная облачность",
        condition_emoji="🌦" if umbrella else "⛅",
        wind_speed_ms=5.0,
        precip_prob=80 if umbrella else 10,
    )
    return DayWeatherSummary(
        city_name="Berlin",
        target_date=date(2026, 11, 24),
        timezone="Europe/Berlin",
        active_start_hour=8,
        active_end_hour=21,
        morning=slot.model_copy(update={"label": "Утро", "hour": 8}),
        day=slot,
        evening=slot.model_copy(update={"label": "Вечер", "hour": 21}),
        temp_min=8.0,
        temp_max=12.0,
        feels_min=6.0,
        feels_max=10.0,
        feels_avg=8.5,
        max_wind_ms=6.0,
        max_gusts_ms=9.0,
        max_precip_prob=80 if umbrella else 10,
        total_precip_mm=2.5 if umbrella else 0.0,
        total_snow_cm=0.0,
        max_uv=2.0,
        avg_humidity=75,
        alerts=WeatherAlerts(
            umbrella_required=umbrella,
            rain_window=rain_window,
        ),
    )


def _settings(*, api_key: str = "test-key", fallback_api_key: str = "") -> Settings:
    return Settings(
        bot_token="123456:TEST",
        llm_api_key=api_key,
        llm_base_url="https://mock.primary.local/v1",
        llm_model="test-llama-70b",
        llm_fallback_api_key=fallback_api_key,
        llm_fallback_base_url="https://mock.fallback.local/v1",
        llm_fallback_model="fallback-cerebras",
        llm_timeout_seconds=5.0,
    )


async def test_ai_advisor_parses_structured_json_and_fences() -> None:
    payload = {
        "headline": "Свежо и ветрено — бери бежевый тренч",
        "top": "Хлопковая футболка и тёплое худи",
        "outerwear": "Бежевый тренч из твоего гардероба",
        "bottom": "Тёмные джинсы",
        "footwear": "Кожаные кроссовки (замшевые челси сегодня отложи)",
        "accessories": ["Лёгкий шарф"],
        "pro_tip": "Если пойдёт морось, тренч защитит лучше замши.",
    }
    fenced = f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": fenced}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        advisor = HybridOutfitAdvisor(client, _settings())
        user = UserProfile(
            user_id=1,
            wardrobe_text="Бежевый тренч, кожаные кроссовки, замшевые челси",
        )
        advice = await advisor.advise(_make_summary(), user)

    assert advice.source == "ai"
    assert advice.model_name == "test-llama-70b"
    assert "тренч" in advice.outerwear.lower()
    assert advice.accessories == ["Лёгкий шарф"]


async def test_ai_advisor_guardrail_reinjects_umbrella_if_llm_forgets() -> None:
    llm_json = json.dumps(
        {
            "headline": "Прохладный день",
            "top": "Лонгслив и свитер",
            "outerwear": "Ветровка с капюшоном",
            "bottom": "Джинсы",
            "footwear": "Кожаные ботинки",
            "accessories": [],
            "pro_tip": "Одевайся теплее к вечеру.",
        },
        ensure_ascii=False,
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": llm_json}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        advisor = HybridOutfitAdvisor(client, _settings())
        user = UserProfile(user_id=1)
        summary = _make_summary(umbrella=True, rain_window="14:00–17:00")
        advice = await advisor.advise(summary, user)

    assert advice.source == "ai"
    assert any("зонт" in item.lower() and "14:00–17:00" in item for item in advice.accessories)


async def test_ai_advisor_falls_back_to_rules_on_http_500_and_timeout() -> None:
    def fail_500(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "upstream down"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail_500)) as client:
        advisor = HybridOutfitAdvisor(client, _settings())
        advice = await advisor.advise(_make_summary(umbrella=True), UserProfile(user_id=1))
        assert advice.source == "rules"
        assert advice.model_name is None

    def fail_timeout(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail_timeout)) as client:
        advisor = HybridOutfitAdvisor(client, _settings())
        advice = await advisor.advise(_make_summary(), UserProfile(user_id=1))
        assert advice.source == "rules"


async def test_ai_advisor_skips_http_when_unconfigured_or_disabled() -> None:
    called = False

    def should_not_be_called(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(should_not_be_called)) as client:
        no_key_advisor = HybridOutfitAdvisor(client, _settings(api_key=""))
        res1 = await no_key_advisor.advise(_make_summary(), UserProfile(user_id=1))
        assert res1.source == "rules"
        assert called is False

        disabled_advisor = HybridOutfitAdvisor(client, _settings(api_key="key"))
        res2 = await disabled_advisor.advise(_make_summary(), UserProfile(user_id=1, use_ai=False))
        assert res2.source == "rules"
        assert called is False


async def test_answer_question_returns_text_and_handles_failures() -> None:
    def ok_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "В ветровке вечером будет прохладно."}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(ok_handler)) as client:
        advisor = HybridOutfitAdvisor(client, _settings())
        reply = await advisor.answer_question(
            "В ветровке не замерзну?",
            _make_summary(),
            UserProfile(user_id=1),
        )
        assert reply == "В ветровке вечером будет прохладно."

    def err_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(err_handler)) as client:
        advisor = HybridOutfitAdvisor(client, _settings())
        reply = await advisor.answer_question("Вопрос?", _make_summary(), UserProfile(user_id=1))
        assert reply is None


async def test_ai_advisor_failover_from_primary_429_to_fallback_provider() -> None:
    calls: list[str] = []
    fallback_json = json.dumps(
        {
            "headline": "Дождливый день",
            "top": "Футболка и свитшот",
            "outerwear": "Непромокаемая ветровка",
            "bottom": "Тёмные джинсы",
            "footwear": "Кожаные ботинки",
            "accessories": [],
            "pro_tip": "Выбирай верх с капюшоном.",
        },
        ensure_ascii=False,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "mock.primary.local":
            return httpx.Response(429, json={"error": "rate limit"})
        return httpx.Response(200, json={"choices": [{"message": {"content": fallback_json}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        settings = _settings(api_key="primary-key", fallback_api_key="fallback-key")
        advisor = HybridOutfitAdvisor(client, settings)
        summary = _make_summary(umbrella=True, rain_window="14:00–17:00")
        advice = await advisor.advise(summary, UserProfile(user_id=1))

    assert calls == ["mock.primary.local", "mock.fallback.local"]
    assert advice.source == "ai"
    assert advice.model_name == "fallback-cerebras"
    assert any("зонт" in item.lower() for item in advice.accessories)


async def test_ai_advisor_all_providers_fail_falls_back_to_rules() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "mock.primary.local":
            return httpx.Response(503, json={"error": "overloaded"})
        return httpx.Response(500, json={"error": "fallback down"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        settings = _settings(api_key="primary-key", fallback_api_key="fallback-key")
        advisor = HybridOutfitAdvisor(client, settings)
        advice = await advisor.advise(_make_summary(), UserProfile(user_id=1))

    assert calls == ["mock.primary.local", "mock.fallback.local"]
    assert advice.source == "rules"
    assert advice.model_name is None


async def test_answer_question_failover_to_fallback_provider() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "mock.primary.local":
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Лучше накинуть ветровку."}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        settings = _settings(api_key="primary-key", fallback_api_key="fallback-key")
        advisor = HybridOutfitAdvisor(client, settings)
        reply = await advisor.answer_question(
            "Ветровка нужна?",
            _make_summary(),
            UserProfile(user_id=1),
        )

    assert calls == ["mock.primary.local", "mock.fallback.local"]
    assert reply == "Лучше накинуть ветровку."


async def test_ai_advisor_bike_guardrail_adds_raincoat_not_umbrella() -> None:
    captured_payload: dict[str, object] = {}
    llm_json = json.dumps(
        {
            "headline": "Свежо",
            "top": "Футболка и кофта",
            "outerwear": "Лёгкая куртка",
            "bottom": "Джинсы",
            "footwear": "Кроссовки",
            "accessories": [],
            "pro_tip": "Осторожнее на дороге.",
        },
        ensure_ascii=False,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"choices": [{"message": {"content": llm_json}}]})

    leg = CommuteLegSummary(
        hour=8,
        temp=10.0,
        apparent_temp=8.0,
        wind_speed_ms=7.0,
        wind_gusts_ms=10.0,
        precip_prob=10,
        precipitation_mm=0.0,
        condition_emoji="⛅",
        condition_text="Облачно",
        is_rain=False,
    )
    commute = CommuteSummary(
        origin_name="Дом",
        destination_name="Офис",
        transport_mode="bike",
        way_there=leg,
        at_destination_temp_min=10.0,
        at_destination_temp_max=12.0,
        at_destination_condition_emoji="⛅",
        at_destination_condition_text="Облачно",
        way_back=leg.model_copy(update={"hour": 18, "is_rain": True, "precip_prob": 80}),
        rain_on_way_there=False,
        rain_on_way_back=True,
        wind_warning=True,
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        advisor = HybridOutfitAdvisor(client, _settings())
        advice = await advisor.advise(_make_summary(), UserProfile(user_id=1), commute=commute)

    assert any("дождевик" in item.lower() for item in advice.accessories)
    assert not any("зонт" in item.lower() for item in advice.accessories)
    user_msg = captured_payload["messages"][1]["content"]  # type: ignore[index]
    assert '"transport_mode": "bike"' in user_msg
