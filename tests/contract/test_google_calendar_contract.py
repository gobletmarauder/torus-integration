"""Contract checks for synthetic Google Calendar fixtures."""

import json
from pathlib import Path

import pytest

from tis.integrations.google_calendar import (
    CalendarEventsResponse,
    GoogleEvent,
    GoogleTokenResponse,
)

FIXTURES = Path(__file__).parents[1] / "fixtures/google_calendar"


@pytest.mark.parametrize(
    "name",
    [
        "handoff-review-redacted.json",
        "events-initial.json",
        "events-incremental.json",
        "events-rescheduled.json",
        "events-cancelled.json",
    ],
)
def test_event_fixtures_match_calendar_contract(name: str) -> None:
    document = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    if name == "handoff-review-redacted.json":
        assert GoogleEvent.model_validate(document).id == "synthetic-handoff-event-001"
    else:
        parsed = CalendarEventsResponse.model_validate(document)
        assert parsed.items


def test_token_fixture_matches_oauth_contract() -> None:
    document = json.loads((FIXTURES / "token-success.json").read_text(encoding="utf-8"))
    assert GoogleTokenResponse.model_validate(document).expires_in == 3600


def test_gone_fixture_represents_expired_cursor() -> None:
    document = json.loads((FIXTURES / "sync-token-gone.json").read_text(encoding="utf-8"))
    assert document["error"]["code"] == 410
