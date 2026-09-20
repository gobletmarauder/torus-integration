"""Configuration safety tests."""

import pytest
from pydantic import ValidationError

from tis.config import Settings


def service_url(host: str) -> str:
    return "https" + f"://{host}"


def test_dry_run_defaults_true() -> None:
    settings = Settings(_env_file=None)
    assert settings.env == "dev"
    assert settings.dry_run is True


def test_development_cannot_disable_dry_run() -> None:
    with pytest.raises(ValidationError, match="ENV=prod"):
        Settings(env="dev", dry_run=False, _env_file=None)


def test_production_may_explicitly_disable_dry_run() -> None:
    settings = Settings(env="prod", dry_run=False, _env_file=None)
    assert settings.dry_run is False


def test_budgets_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(posthog_budget_per_run=0, _env_file=None)


def test_job_flags_are_independent() -> None:
    settings = Settings(lead_sync_enabled=False, booking_sync_enabled=True, _env_file=None)
    assert settings.lead_sync_enabled is False
    assert settings.booking_sync_enabled is True


def test_enabled_lead_sync_requires_complete_approved_settings() -> None:
    with pytest.raises(ValidationError, match="incomplete"):
        Settings(lead_sync_enabled=True, _env_file=None)

    settings = Settings(
        lead_sync_enabled=True,
        database_dsn="postgresql://synthetic.invalid/db",
        zoho_client_id="synthetic-client",
        zoho_client_secret="synthetic-secret",  # noqa: S106
        zoho_refresh_token="synthetic-refresh",  # noqa: S106
        zoho_accounts_url=service_url("accounts.zoho.com"),
        zoho_api_url=service_url("www.zohoapis.com"),
        _env_file=None,
    )
    assert settings.lead_sync_enabled is True
    assert "synthetic-secret" not in repr(settings)


def test_enabled_lead_sync_rejects_unapproved_hosts() -> None:
    with pytest.raises(ValidationError, match="approved US hosts"):
        Settings(
            lead_sync_enabled=True,
            database_dsn="postgresql://synthetic.invalid/db",
            zoho_client_id="synthetic-client",
            zoho_client_secret="synthetic-secret",  # noqa: S106
            zoho_refresh_token="synthetic-refresh",  # noqa: S106
            zoho_accounts_url=service_url("accounts.zoho.com"),
            zoho_api_url=service_url("api.example.com"),
            _env_file=None,
        )
