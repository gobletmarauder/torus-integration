"""Configuration safety tests."""

import pytest
from pydantic import ValidationError

from tis.config import Settings


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
    settings = Settings(lead_sync_enabled=True, booking_sync_enabled=False, _env_file=None)
    assert settings.lead_sync_enabled is True
    assert settings.booking_sync_enabled is False
