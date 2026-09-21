"""Validated service configuration loaded exclusively from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from tempfile import gettempdir
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

    lead_sync_interval_seconds: int = Field(default=30, ge=30)
    booking_sync_interval_seconds: int = Field(default=120, ge=120)
    host_health_interval_seconds: int = Field(default=300, ge=300)
    keepalive_interval_seconds: int = Field(default=86_400, ge=86_400)
    scheduler_watchdog_path: Path = Field(
        default_factory=lambda: Path(gettempdir()) / "tis-scheduler.watchdog"
    )
    scheduler_watchdog_max_age_seconds: int = Field(default=90, ge=60)

    posthog_budget_per_run: int = Field(default=25, gt=0)
    posthog_budget_per_day: int = Field(default=200, gt=0)
    betterstack_budget_per_run: int = Field(default=10, gt=0)
    betterstack_budget_per_day: int = Field(default=400, gt=0)
    zoho_create_budget_per_run: int = Field(default=25, gt=0, le=25)
    zoho_create_budget_per_day: int = Field(default=200, gt=0)
    zoho_booking_budget_per_run: int = Field(default=10, gt=0, le=10)
    zoho_booking_budget_per_day: int = Field(default=100, gt=0)

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
    zoho_booking_field_map_path: Path = Path("config/zoho_booking_fields.toml")
    google_service_account_email: SecretStr | None = None
    google_service_account_private_key: SecretStr | None = None
    google_impersonated_user: SecretStr | None = None
    google_calendar_id: SecretStr | None = None
    google_token_url: HttpUrl | None = None
    google_calendar_api_url: HttpUrl | None = None
    google_booking_lookback_days: int = Field(default=7, ge=7, le=7)
    cloudflare_access_team_domain: str | None = None
    cloudflare_access_audience: SecretStr | None = None
    tis_digest: str = "unknown"

    @model_validator(mode="after")
    def require_safe_dry_run(self) -> Settings:
        """Reject live writes outside production; this has no side effects."""
        if self.env != "prod" and not self.dry_run:
            raise ValueError("DRY_RUN may be false only when ENV=prod")
        if self.lead_sync_enabled or self.booking_sync_enabled:
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
        if self.booking_sync_enabled:
            google_required = (
                self.google_service_account_email,
                self.google_service_account_private_key,
                self.google_impersonated_user,
                self.google_calendar_id,
                self.google_token_url,
                self.google_calendar_api_url,
            )
            if any(value is None for value in google_required):
                raise ValueError("booking sync settings are incomplete")
            google_hosts = {
                str(self.google_token_url.host if self.google_token_url else ""),
                str(self.google_calendar_api_url.host if self.google_calendar_api_url else ""),
            }
            if google_hosts != {"oauth2.googleapis.com", "www.googleapis.com"}:
                raise ValueError("Google URLs must use the approved hosts")
        if self.keepalive_enabled:
            if not self.database_dsn or self.betterstack_keepalive_url is None:
                raise ValueError("keepalive settings are incomplete")
        if self.host_health_enabled:
            if not self.database_dsn or self.betterstack_host_health_url is None:
                raise ValueError("host health settings are incomplete")
        if self.cloudflare_access_team_domain is not None:
            domain = self.cloudflare_access_team_domain.lower().rstrip(".")
            if domain != "torusmesh.cloudflareaccess.com":
                raise ValueError("Cloudflare Access must use the approved team domain")
            self.cloudflare_access_team_domain = domain
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide validated settings without external side effects."""
    return Settings()
