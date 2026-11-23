from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class LLMProviderConfig:
    """Configuration for a single OpenAI-compatible LLM provider."""

    name: str
    api_key: str
    base_url: str
    model: str


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    bot_token: str
    allowed_user_ids_raw: str = Field(default="", alias="ALLOWED_USER_IDS")
    db_path: Path = Path("data/bot.db")
    log_level: str = "INFO"

    llm_api_key: str = ""
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "llama-3.3-70b-versatile"

    llm_fallback_api_key: str = ""
    llm_fallback_base_url: str = "https://api.cerebras.ai/v1"
    llm_fallback_model: str = "gpt-oss-120b"

    llm_timeout_seconds: float = 15.0

    @property
    def allowed_user_ids(self) -> set[int]:
        """Parse comma-separated Telegram user IDs; empty set means open access."""
        ids: set[int] = set()
        for part in self.allowed_user_ids_raw.split(","):
            cleaned = part.strip()
            if not cleaned:
                continue
            try:
                ids.add(int(cleaned))
            except ValueError:
                continue
        return ids

    @property
    def llm_providers(self) -> list[LLMProviderConfig]:
        """Return configured OpenAI-compatible LLM providers in priority order."""
        providers: list[LLMProviderConfig] = []
        if self.llm_api_key.strip():
            providers.append(
                LLMProviderConfig(
                    name="primary",
                    api_key=self.llm_api_key.strip(),
                    base_url=self.llm_base_url.strip(),
                    model=self.llm_model.strip(),
                )
            )
        if self.llm_fallback_api_key.strip():
            providers.append(
                LLMProviderConfig(
                    name="fallback",
                    api_key=self.llm_fallback_api_key.strip(),
                    base_url=self.llm_fallback_base_url.strip(),
                    model=self.llm_fallback_model.strip(),
                )
            )
        return providers

    @property
    def llm_configured(self) -> bool:
        """Return True when at least one LLM API key is provided."""
        return bool(self.llm_providers)

    @property
    def llm_display_label(self) -> str:
        """Human-readable label listing active model chain."""
        providers = self.llm_providers
        if not providers:
            return "none"
        return " → ".join(p.model for p in providers)
