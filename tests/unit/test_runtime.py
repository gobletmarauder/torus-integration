"""Runtime dependency-assembly tests."""

import pytest

from tis.config import Settings
from tis.runtime import build_runtime


def url(host: str) -> str:
    return "https" + f"://{host}"


def test_runtime_requires_database_and_builds_fresh_write_contexts() -> None:
    with pytest.raises(RuntimeError, match="DATABASE_DSN"):
        build_runtime(Settings(_env_file=None))
    runtime = build_runtime(
        Settings(database_dsn="postgresql://synthetic.invalid/db", _env_file=None)
    )
    assert runtime.lead is None and runtime.booking is None
    first = runtime.new_writes()
    second = runtime.new_writes()
    assert first is not second
    assert first.state is runtime.state and first.audit is runtime.audit


def test_runtime_builds_enabled_lead_and_booking_contexts() -> None:
    settings = Settings(
        lead_sync_enabled=True,
        booking_sync_enabled=True,
        database_dsn="postgresql://synthetic.invalid/db",
        zoho_client_id="synthetic-client",
        zoho_client_secret="synthetic-secret",  # noqa: S106
        zoho_refresh_token="synthetic-refresh",  # noqa: S106
        zoho_accounts_url=url("accounts.zoho.com"),
        zoho_api_url=url("www.zohoapis.com"),
        google_service_account_email="reader@example.invalid",
        google_service_account_private_key="synthetic-key",
        google_impersonated_user="owner@example.invalid",
        google_calendar_id="calendar@example.invalid",
        google_token_url=url("oauth2.googleapis.com") + "/token",
        google_calendar_api_url=url("www.googleapis.com"),
        _env_file=None,
    )
    runtime = build_runtime(settings)
    assert runtime.lead is not None and runtime.booking is not None
    assert runtime.booking.lookback_days == 7
