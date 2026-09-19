"""Validated service configuration loaded exclusively from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings; constructing this object reads environment variables only."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    env: Literal["dev", "prod"] = "dev"
    dry_run: bool = True
    kill_switch: bool = False

    lead_sync_enabled: bool = False
    booking_sync_enabled: bool = False
    keepalive_enabled: bool = False
    host_health_enabled: bool = False

    posthog_budget_per_run: int = Field(default=25, gt=0)
    posthog_budget_per_day: int = Field(default=200, gt=0)
    betterstack_budget_per_run: int = Field(default=10, gt=0)
    betterstack_budget_per_day: int = Field(default=400, gt=0)

    database_dsn: str | None = None
    posthog_api_key: str | None = None
    posthog_host: HttpUrl | None = None
    betterstack_keepalive_url: HttpUrl | None = None
    betterstack_host_health_url: HttpUrl | None = None
    betterstack_backup_url: HttpUrl | None = None

    @model_validator(mode="after")
    def require_safe_dry_run(self) -> Settings:
        """Reject live writes outside production; this has no side effects."""
        if self.env != "prod" and not self.dry_run:
            raise ValueError("DRY_RUN may be false only when ENV=prod")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide validated settings without external side effects."""
    return Settings()
