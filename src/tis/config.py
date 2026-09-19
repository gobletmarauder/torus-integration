"""Validated service configuration loaded exclusively from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, model_validator
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
    zoho_create_budget_per_run: int = Field(default=25, gt=0, le=25)
    zoho_create_budget_per_day: int = Field(default=200, gt=0)

    database_dsn: str | None = None
    posthog_api_key: str | None = None
    posthog_host: HttpUrl | None = None
    betterstack_keepalive_url: HttpUrl | None = None
    betterstack_host_health_url: HttpUrl | None = None
    betterstack_backup_url: HttpUrl | None = None
    zoho_client_id: SecretStr | None = None
    zoho_client_secret: SecretStr | None = None
    zoho_refresh_token: SecretStr | None = None
    zoho_accounts_url: HttpUrl | None = None
    zoho_api_url: HttpUrl | None = None
    zoho_api_version: Literal["v8"] = "v8"
    zoho_lead_field_map_path: Path = Path("config/zoho_lead_fields.toml")
    allow_test_sync: bool = False

    @model_validator(mode="after")
    def require_safe_dry_run(self) -> Settings:
        """Reject live writes outside production; this has no side effects."""
        if self.env != "prod" and not self.dry_run:
            raise ValueError("DRY_RUN may be false only when ENV=prod")
        if self.lead_sync_enabled:
            required = (
                self.database_dsn,
                self.zoho_client_id,
                self.zoho_client_secret,
                self.zoho_refresh_token,
                self.zoho_accounts_url,
                self.zoho_api_url,
            )
            if any(value is None for value in required):
                raise ValueError("lead sync settings are incomplete")
            hosts = {
                str(self.zoho_accounts_url.host if self.zoho_accounts_url else ""),
                str(self.zoho_api_url.host if self.zoho_api_url else ""),
            }
            if hosts != {"accounts.zoho.com", "www.zohoapis.com"}:
                raise ValueError("Zoho URLs must use the approved US hosts")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide validated settings without external side effects."""
    return Settings()
