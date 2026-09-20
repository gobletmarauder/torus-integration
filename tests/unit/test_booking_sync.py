"""Booking job cursor and deferred-change safety tests."""

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import tis.jobs.booking_sync as booking_sync
from tis.guards import WriteContext
from tis.http import ControlledClient
from tis.integrations.google_calendar import (
    CalendarEventsResponse,
    GoogleCalendarAuth,
    GoogleEvent,
    SyncTokenGone,
)
from tis.integrations.zoho import ZohoAuth
from tis.jobs.booking_sync import CURSOR_KEY, BookingSyncContext
from tis.mapping.booking_parser import load_booking_field_map
from tis.mapping.lead_to_zoho import load_field_map

ROOT = Path(__file__).parents[2]
START = datetime(2026, 1, 20, 16, tzinfo=UTC)


class State:
    def __init__(self, cursor: Any = None, *, kill: bool = False) -> None:
        self.cursor = cursor
        self.kill = kill
        self.writes: list[tuple[str, Any]] = []

    async def get(self, key: str) -> Any:
        assert key == CURSOR_KEY
        return self.cursor

    async def set(self, key: str, value: Any) -> None:
        self.writes.append((key, value))

    async def kill_switch_on(self) -> bool:
        return self.kill


class Audit:
    async def status(self, source: str, external_id: str, action: str) -> str | None:
        return None

    async def successful_today(self, source: str, action: str, since: datetime) -> int:
        return 0

    async def claim(self, source: str, external_id: str, action: str) -> bool:
        return True

    async def record(
        self,
        source: str,
        external_id: str,
        action: str,
        status: str,
        *,
        error: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        return None


def event(*, status: str = "confirmed", start: datetime = START) -> GoogleEvent:
    return GoogleEvent.model_validate(
        {
            "id": "synthetic-event",
            "status": status,
            "summary": "Handoff Review (Example Person)",
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": start.replace(minute=30).isoformat()},
            "attendees": [{"email": "prospect@example.com"}],
            "organizer": {"email": "owner@example.invalid", "self": True},
        }
    )


def context(state: State, *, dry_run: bool = False) -> BookingSyncContext:
    token_url = "https" + "://oauth2.googleapis.com/token"
    synthetic_value = "synthetic"
    writes = WriteContext(
        dry_run=dry_run,
        state=state,  # type: ignore[arg-type]
        audit=Audit(),  # type: ignore[arg-type]
        per_run_budgets={("google_calendar", "sync_booking"): 10},
        per_day_budgets={("google_calendar", "sync_booking"): 100},
    )
    return BookingSyncContext(
        writes=writes,
        state=state,  # type: ignore[arg-type]
        http=ControlledClient(),
        google_auth=GoogleCalendarAuth(
            service_account_email="reader@example.invalid",
            private_key="unused",
            impersonated_user="owner@example.invalid",
            token_url=token_url,
        ),
        zoho_auth=ZohoAuth(
            client_id="synthetic",
            client_secret=synthetic_value,
            refresh_token=synthetic_value,
            accounts_url="https" + "://accounts.zoho.com",
        ),
        google_api_url="https" + "://www.googleapis.com",
        calendar_id="calendar@example.invalid",
        zoho_api_url="https" + "://www.zohoapis.com",
        lead_fields=load_field_map(ROOT / "config/zoho_lead_fields.toml"),
        booking_fields=load_booking_field_map(ROOT / "config/zoho_booking_fields.toml"),
    )


async def test_success_commits_cursor_only_after_write(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fetched(*_args: Any) -> tuple[list[GoogleEvent], str]:
        return [event()], "next-token"

    async def synced(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(booking_sync, "_fetch_events", fetched)
    monkeypatch.setattr(booking_sync, "sync_booking", synced)
    state = State()
    ctx = context(state)
    try:
        result = await booking_sync.run(ctx)
    finally:
        await ctx.http.aclose()
    assert result.succeeded == 1 and result.failed == 0
    assert state.writes[0][1]["sync_token"] == "next" + "-token"


async def test_dry_run_and_reschedule_do_not_advance_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fetched(*_args: Any) -> tuple[list[GoogleEvent], str]:
        return [event(start=START.replace(hour=17))], "next-token"

    async def synced(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(booking_sync, "_fetch_events", fetched)
    monkeypatch.setattr(booking_sync, "sync_booking", synced)
    state = State(
        {"sync_token": "old", "events": {"synthetic-event": {"start": START.isoformat()}}}
    )
    ctx = context(state, dry_run=True)
    try:
        result = await booking_sync.run(ctx)
    finally:
        await ctx.http.aclose()
    assert result.failed == 1
    assert state.writes == []


async def test_cancelled_prior_event_is_deferred(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fetched(*_args: Any) -> tuple[list[GoogleEvent], str]:
        return [event(status="cancelled")], "next-token"

    monkeypatch.setattr(booking_sync, "_fetch_events", fetched)
    state = State({"events": {"synthetic-event": {"start": START.isoformat()}}})
    ctx = context(state)
    try:
        result = await booking_sync.run(ctx)
    finally:
        await ctx.http.aclose()
    assert result.failed == 1 and not state.writes


class Calendar:
    def __init__(self, pages: list[CalendarEventsResponse | Exception]) -> None:
        self.pages = pages
        self.calls: list[tuple[str | None, str | None, datetime | None]] = []

    async def events_page(
        self,
        *,
        sync_token: str | None,
        page_token: str | None,
        time_min: datetime | None,
    ) -> CalendarEventsResponse:
        self.calls.append((sync_token, page_token, time_min))
        value = self.pages.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


async def test_pages_are_bounded_and_return_final_sync_token() -> None:
    state = State()
    ctx = context(state)
    calendar = Calendar(
        [
            CalendarEventsResponse(items=[event()], nextPageToken="page-2"),
            CalendarEventsResponse(items=[event()], nextSyncToken="final-token"),
        ]
    )
    try:
        events, next_cursor = await booking_sync._fetch_pages(  # noqa: SLF001
            ctx,
            calendar,
            None,  # type: ignore[arg-type]
        )
    finally:
        await ctx.http.aclose()
    assert len(events) == 2 and next_cursor == "final" + "-token"
    assert calendar.calls[0][2] is not None
    assert calendar.calls[1][1] == "page-2"


async def test_expired_incremental_token_recovers_once() -> None:
    state = State()
    ctx = context(state)
    calendar = Calendar(
        [
            SyncTokenGone("expired"),
            CalendarEventsResponse(items=[event()], nextSyncToken="recovered-token"),
        ]
    )
    try:
        events, next_cursor = await booking_sync._fetch_events(  # noqa: SLF001
            ctx,
            calendar,
            "old-token",  # type: ignore[arg-type]
        )
    finally:
        await ctx.http.aclose()
    assert len(events) == 1 and next_cursor == "recovered" + "-token"
    assert calendar.calls[0][0] == "old-token"
    assert calendar.calls[1][0] is None


async def test_second_gone_and_invalid_cursor_fail_typed() -> None:
    state = State({"events": {"bad": {"start": "not-a-date"}}})
    with pytest.raises(Exception, match="stored booking cursor"):
        await booking_sync._load_cursor(state)  # type: ignore[arg-type]  # noqa: SLF001
    ctx = context(State())
    calendar = Calendar([SyncTokenGone("first"), SyncTokenGone("second")])
    try:
        with pytest.raises(SyncTokenGone):
            await booking_sync._fetch_events(  # noqa: SLF001
                ctx,
                calendar,
                "old-token",  # type: ignore[arg-type]
            )
    finally:
        await ctx.http.aclose()


def test_classification_and_cursor_bound_helpers() -> None:
    cursor = booking_sync.BookingCursor(
        events={"synthetic-event": booking_sync.CursorEvent(start=START)}
    )
    assert booking_sync._classify(event(), cursor) == "ignore"  # noqa: SLF001
    unrelated = event()
    unrelated.id = "other"
    unrelated.summary = "Unrelated"
    assert booking_sync._classify(unrelated, cursor) == "ignore"  # noqa: SLF001
    no_time = event()
    no_time.id = "new"
    no_time.start = None
    assert booking_sync._classify(no_time, cursor) == "new"  # noqa: SLF001
    many = {
        str(index): booking_sync.CursorEvent(start=START.replace(microsecond=index))
        for index in range(501)
    }
    assert len(booking_sync._bounded_fingerprints(many)) == 500  # noqa: SLF001
