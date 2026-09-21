"""Configuration safety tests."""

from pathlib import Path

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
    settings = Settings(lead_sync_enabled=False, booking_sync_enabled=False, _env_file=None)
    assert settings.lead_sync_enabled is False
    assert settings.booking_sync_enabled is False


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


def test_enabled_booking_sync_requires_google_settings_and_exact_hosts() -> None:
    common = {
        "booking_sync_enabled": True,
        "database_dsn": "postgresql://synthetic.invalid/db",
        "zoho_client_id": "synthetic-client",
        "zoho_client_secret": "synthetic-secret",
        "zoho_refresh_token": "synthetic-refresh",
        "zoho_accounts_url": service_url("accounts.zoho.com"),
        "zoho_api_url": service_url("www.zohoapis.com"),
        "google_service_account_email": "reader@example.invalid",
        "google_service_account_private_key": "synthetic-private-key",
        "google_impersonated_user": "owner@example.invalid",
        "google_calendar_id": "calendar@example.invalid",
        "google_token_url": service_url("oauth2.googleapis.com") + "/token",
        "google_calendar_api_url": service_url("www.googleapis.com"),
    }
    settings = Settings(**common, _env_file=None)
    assert settings.booking_sync_enabled
    assert "synthetic-private-key" not in repr(settings)
    with pytest.raises(ValidationError, match="approved hosts"):
        Settings(
            **{**common, "google_calendar_api_url": service_url("example.com")}, _env_file=None
        )


def test_m4_intervals_enforce_safe_minimums() -> None:
    with pytest.raises(ValidationError):
        Settings(lead_sync_interval_seconds=29, _env_file=None)
    with pytest.raises(ValidationError):
        Settings(booking_sync_interval_seconds=119, _env_file=None)
    with pytest.raises(ValidationError):
        Settings(host_health_interval_seconds=299, _env_file=None)
    with pytest.raises(ValidationError):
        Settings(keepalive_interval_seconds=86_399, _env_file=None)


def test_enabled_health_jobs_require_database_and_heartbeat() -> None:
    with pytest.raises(ValidationError, match="keepalive settings"):
        Settings(keepalive_enabled=True, _env_file=None)
    with pytest.raises(ValidationError, match="host health settings"):
        Settings(host_health_enabled=True, _env_file=None)
    keepalive = Settings(
        keepalive_enabled=True,
        database_dsn="postgresql://synthetic.invalid/db",
        betterstack_keepalive_url=service_url("uptime.betterstack.com") + "/synthetic",
        _env_file=None,
    )
    assert keepalive.keepalive_enabled


def test_access_team_domain_is_exact_and_audience_is_secret() -> None:
    settings = Settings(
        cloudflare_access_team_domain="torusmesh.cloudflareaccess.com.",
        cloudflare_access_audience="synthetic-audience",
        _env_file=None,
    )
    assert settings.cloudflare_access_team_domain == "torusmesh.cloudflareaccess.com"
    assert "synthetic-audience" not in repr(settings)
    with pytest.raises(ValidationError, match="approved team domain"):
        Settings(cloudflare_access_team_domain="example.com", _env_file=None)


def test_environment_example_matches_settings_and_google_contract() -> None:
    lines = Path(".env.example").read_text(encoding="utf-8").splitlines()
    names = [line.partition("=")[0] for line in lines if line and not line.startswith("#")]
    for field in Settings.model_fields:
        assert names.count(field.upper()) == 1
    assert "GOOGLE_PRIVATE_KEY" not in names
    assert names.count("GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY") == 1
    assert names.count("GOOGLE_TOKEN_URL") == 1
    assert names.count("GOOGLE_CALENDAR_API_URL") == 1
    assert all(line.endswith("=") for line in lines if line and not line.startswith("#"))


def test_environment_files_are_ignored_but_example_is_retained() -> None:
    patterns = Path(".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in patterns
    assert ".env.*" in patterns
    assert "!.env.example" in patterns


def test_r2_endpoint_bucket_and_budgets_are_fail_closed() -> None:
    settings = Settings(
        r2_endpoint=service_url("synthetic-account.r2.cloudflarestorage.com"),
        r2_bucket="torus-backups",
        _env_file=None,
    )
    assert settings.r2_upload_budget_per_run == 1
    assert settings.r2_retention_budget_per_day == 1
    with pytest.raises(ValidationError, match="account-scoped"):
        Settings(r2_endpoint=service_url("example.com"), _env_file=None)
    with pytest.raises(ValidationError, match="torus-backups"):
        Settings(r2_bucket="different-bucket", _env_file=None)
    with pytest.raises(ValidationError):
        Settings(r2_upload_budget_per_day=2, _env_file=None)
