from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from pydantic import ValidationError

from weather_wardrobe.config import LLMProviderConfig, Settings
from weather_wardrobe.models import DayWeatherSummary, OutfitAdvice, UserProfile
from weather_wardrobe.services.rule_advisor import RuleBasedAdvisor

logger = logging.getLogger(__name__)

OUTFIT_SYSTEM_PROMPT = """Ты — практичный персональный стилист и погодный ассистент в Telegram.
Твоя задача: на основе точных метеоданных, термопрофиля пользователя и списка его реальных вещей
составить конкретный, лаконичный и реалистичный совет по одежде на день на русском языке.

Правила:
1. Если указан личный гардероб (wardrobe_text), опирайся на реальные вещи пользователя
   и отсекай неподходящие материалы (не советуй замшу, белую ткань или сетку в дождь/снег).
2. Учитывай thermal_comfort_offset: отрицательное значение значит, что человек мёрзнет
   быстрее нормы, положительное — что ему обычно жарче, чем другим.
3. Учитывай перепад температур между утром, днём и вечером (многослойность при перепаде).
4. Если umbrella_required = true, обязательно добавь зонт в accessories и учти осадки.
5. Отвечай СТРОГО валидным JSON без markdown-обрамления и без лишнего текста:
{
  "headline": "короткий заголовок сути дня (до 70 символов)",
  "top": "базовый и средний слой",
  "outerwear": "верхняя одежда",
  "bottom": "низ",
  "footwear": "обувь",
  "accessories": ["список коротких пунктов, пустой если ничего не нужно"],
  "pro_tip": "один практичный совет на 1-2 предложения"
}"""

QA_SYSTEM_PROMPT = """Ты — практичный погодный ассистент в Telegram.
Отвечай кратко, по делу и на русском языке (3-5 предложений максимум),
опираясь строго на переданный прогноз погоды на сегодня, термопрофиль и гардероб пользователя.
Не выдумывай метеоданные, которых нет в контексте."""

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _strip_json_fences(raw: str) -> str:
    return _FENCE_RE.sub("", raw.strip()).strip()


def _build_weather_context(
    summary: DayWeatherSummary,
    user: UserProfile,
    recent_feedback: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "city": summary.city_name,
        "date": summary.target_date.isoformat(),
        "active_hours": f"{summary.active_start_hour:02d}:00-{summary.active_end_hour:02d}:00",
        "slots": {
            "morning": summary.morning.model_dump(),
            "day": summary.day.model_dump(),
            "evening": summary.evening.model_dump(),
        },
        "summary": {
            "temp_min_c": summary.temp_min,
            "temp_max_c": summary.temp_max,
            "feels_min_c": summary.feels_min,
            "feels_max_c": summary.feels_max,
            "feels_avg_c": summary.feels_avg,
            "max_wind_ms": summary.max_wind_ms,
            "max_gusts_ms": summary.max_gusts_ms,
            "max_precip_prob_pct": summary.max_precip_prob,
            "total_precip_mm": summary.total_precip_mm,
            "total_snow_cm": summary.total_snow_cm,
            "max_uv": summary.max_uv,
            "avg_humidity_pct": summary.avg_humidity,
        },
        "alerts": summary.alerts.model_dump(),
        "user_profile": {
            "thermal_comfort_offset_c": user.comfort_offset,
            "wardrobe_text": user.wardrobe_text or "Не указан (подбери универсальные базовые вещи)",
            "recent_feedback": recent_feedback or [],
        },
    }


def _enforce_safety_invariants(advice: OutfitAdvice, summary: DayWeatherSummary) -> OutfitAdvice:
    """Deterministic post-check ensuring critical safety accessories are never dropped by LLM."""
    accessories = list(advice.accessories)
    joined = " ".join(accessories).lower()

    if summary.alerts.umbrella_required and "зонт" not in joined:
        rain_note = (
            f"☂️ Зонт (дождь {summary.alerts.rain_window})"
            if summary.alerts.rain_window
            else "☂️ Зонт"
        )
        accessories.insert(0, rain_note)
        joined = " ".join(accessories).lower()

    if summary.alerts.high_uv and not any(
        token in joined for token in ("очк", "spf", "солнц", "крем")
    ):
        accessories.append("🕶 Солнцезащитные очки / SPF")
        joined = " ".join(accessories).lower()

    if summary.feels_min <= -3.0 and not any(
        token in joined for token in ("шапк", "перчат")
    ):
        accessories.append("🧤 Перчатки и тёплая шапка")

    return advice.model_copy(update={"accessories": accessories})


class HybridOutfitAdvisor:
    """Combines OpenAI-compatible LLM reasoning with deterministic fallback and guardrails."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: Settings,
        rule_advisor: RuleBasedAdvisor | None = None,
    ) -> None:
        self.http = http_client
        self.settings = settings
        self.rule_advisor = rule_advisor or RuleBasedAdvisor()

    async def _call_chat_completion(
        self,
        provider: LLMProviderConfig,
        messages: list[dict[str, str]],
        *,
        json_mode: bool,
        temperature: float,
        max_tokens: int,
    ) -> str:
        endpoint = f"{provider.base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": provider.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        resp = await self.http.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {provider.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.settings.llm_timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise KeyError("LLM response contained no choices")
        content = choices[0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM response content is empty")
        return content

    def _parse_outfit_json(self, raw_content: str, model_name: str) -> OutfitAdvice:
        cleaned = _strip_json_fences(raw_content)
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            raise ValueError("LLM JSON root is not an object")
        accessories = parsed.get("accessories")
        if isinstance(accessories, str):
            parsed["accessories"] = [accessories] if accessories.strip() else []
        elif accessories is None:
            parsed["accessories"] = []
        parsed["source"] = "ai"
        parsed["model_name"] = model_name
        return OutfitAdvice.model_validate(parsed)

    async def advise(
        self,
        summary: DayWeatherSummary,
        user: UserProfile,
        recent_feedback: list[dict[str, Any]] | None = None,
    ) -> OutfitAdvice:
        baseline = self.rule_advisor.advise(summary, user)
        providers = self.settings.llm_providers
        if not providers or not user.use_ai:
            return baseline

        context_json = json.dumps(
            _build_weather_context(summary, user, recent_feedback),
            ensure_ascii=False,
        )
        messages = [
            {"role": "system", "content": OUTFIT_SYSTEM_PROMPT},
            {"role": "user", "content": context_json},
        ]

        for provider in providers:
            try:
                raw_content = await self._call_chat_completion(
                    provider,
                    messages,
                    json_mode=True,
                    temperature=0.35,
                    max_tokens=550,
                )
                advice = self._parse_outfit_json(raw_content, provider.model)
                return _enforce_safety_invariants(advice, summary)
            except (
                httpx.HTTPError,
                TimeoutError,
                json.JSONDecodeError,
                ValidationError,
                KeyError,
                ValueError,
            ) as exc:
                logger.warning(
                    "LLM provider '%s' (%s) failed (%s); trying next fallback.",
                    provider.name,
                    provider.model,
                    exc,
                )

        return baseline

    async def answer_question(
        self,
        question: str,
        summary: DayWeatherSummary,
        user: UserProfile,
    ) -> str | None:
        """Answer a free-text weather/outfit follow-up question using today's forecast."""
        providers = self.settings.llm_providers
        if not providers or not user.use_ai:
            return None

        context_json = json.dumps(_build_weather_context(summary, user), ensure_ascii=False)
        messages = [
            {"role": "system", "content": QA_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Контекст погоды и профиля:\n{context_json}\n\n"
                    f"Вопрос пользователя: {question}"
                ),
            },
        ]

        for provider in providers:
            try:
                reply = await self._call_chat_completion(
                    provider,
                    messages,
                    json_mode=False,
                    temperature=0.4,
                    max_tokens=400,
                )
                return reply.strip()
            except (httpx.HTTPError, TimeoutError, KeyError, ValueError) as exc:
                logger.warning(
                    "LLM Q&A provider '%s' (%s) failed (%s); trying next fallback.",
                    provider.name,
                    provider.model,
                    exc,
                )

        return None
