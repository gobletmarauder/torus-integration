"""Incremental, guarded Google Calendar to Zoho booking synchronization."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tis.errors import DuplicateWrite, KillSwitchOn
from tis.guards import WriteContext
from tis.http import ControlledClient
from tis.integrations.google_calendar import (
    GoogleCalendarAuth,
    GoogleCalendarClient,
    GoogleEvent,
    SyncTokenGone,
)
from tis.integrations.zoho import ZohoAuth, sync_booking
from tis.log import get_logger
from tis.mapping.booking_parser import (
    BookingFieldMap,
    BookingParseError,
    is_handoff_review,
    parse_booking,
)
from tis.mapping.lead_to_zoho import ZohoFieldMap
from tis.state import StateStore

CURSOR_KEY = "google_calendar:handoff_review"
MAX_PAGES = 10
MAX_CURSOR_EVENTS = 500
_LOG = get_logger("jobs.booking_sync")


class CursorEvent(BaseModel):
    """Bounded non-personal fingerprint for change classification."""

    model_config = ConfigDict(extra="ignore")

    start: datetime
    status: Literal["confirmed"] = "confirmed"


class BookingCursor(BaseModel):
    """Incremental Google cursor stored in integration_state."""

    model_config = ConfigDict(extra="ignore")

    sync_token: str | None = None
    events: dict[str, CursorEvent] = Field(default_factory=dict)


@dataclass(frozen=True)
class JobResult:
    """Non-personal counters returned by a booking sync run."""

    selected: int
    succeeded: int
    skipped: int
    failed: int


@dataclass
class BookingSyncContext:
    """Dependencies and validated settings for one booking synchronization run."""

    writes: WriteContext
    state: StateStore
    http: ControlledClient
    google_auth: GoogleCalendarAuth
    zoho_auth: ZohoAuth
    google_api_url: str
    calendar_id: str
    zoho_api_url: str
    lead_fields: ZohoFieldMap
    booking_fields: BookingFieldMap
    lookback_days: int = 7
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


async def run(ctx: BookingSyncContext) -> JobResult:
    """Read Calendar changes and apply guarded Zoho writes; this updates cursor state."""
    cursor = await _load_cursor(ctx.state)
    calendar = GoogleCalendarClient(
        http=ctx.http,
        auth=ctx.google_auth,
        api_url=ctx.google_api_url,
        calendar_id=ctx.calendar_id,
    )
    events, next_sync_token = await _fetch_events(ctx, calendar, cursor.sync_token)
    succeeded = skipped = failed = 0
    fingerprints = dict(cursor.events)
    for event in events:
        outcome = _classify(event, cursor)
        if outcome == "ignore":
            skipped += 1
            continue
        if outcome in {"rescheduled", "cancelled"}:
            failed += 1
            _LOG.error("booking_change_deferred", extra={"fields": {"action": outcome}})
            continue
        try:
            booking = parse_booking(event)
            await sync_booking(
                ctx.writes,
                booking,
                ctx.lead_fields,
                ctx.booking_fields,
                ctx.http,
                ctx.zoho_auth,
                api_url=ctx.zoho_api_url,
            )
            if ctx.writes.dry_run:
                skipped += 1
                continue
            fingerprints[event.id] = CursorEvent(start=booking.start)
            succeeded += 1
        except DuplicateWrite:
            if event.start and event.start.date_time:
                fingerprints[event.id] = CursorEvent(start=event.start.date_time)
            skipped += 1
        except KillSwitchOn:
            skipped += 1
            failed += 1
        except Exception as error:
            failed += 1
            _LOG.error(
                "booking_sync_item_failed",
                extra={"fields": {"error": type(error).__name__}},
            )
    if failed == 0 and not ctx.writes.dry_run:
        await ctx.state.set(
            CURSOR_KEY,
            BookingCursor(
                sync_token=next_sync_token,
                events=_bounded_fingerprints(fingerprints),
            ).model_dump(mode="json"),
        )
    return JobResult(len(events), succeeded, skipped, failed)


async def _load_cursor(state: StateStore) -> BookingCursor:
    value = await state.get(CURSOR_KEY)
    if value is None:
        return BookingCursor()
    try:
        return BookingCursor.model_validate(value)
    except ValidationError as error:
        raise BookingParseError("stored booking cursor was invalid") from error


async def _fetch_events(
    ctx: BookingSyncContext,
    calendar: GoogleCalendarClient,
    sync_token: str | None,
) -> tuple[list[GoogleEvent], str]:
    try:
        return await _fetch_pages(ctx, calendar, sync_token)
    except SyncTokenGone:
        if not sync_token:
            raise
        return await _fetch_pages(ctx, calendar, None)


async def _fetch_pages(
    ctx: BookingSyncContext,
    calendar: GoogleCalendarClient,
    sync_token: str | None,
) -> tuple[list[GoogleEvent], str]:
    events: list[GoogleEvent] = []
    page_token: str | None = None
    for _ in range(MAX_PAGES):
        time_min = None
        if not sync_token:
            time_min = ctx.clock().astimezone(UTC) - timedelta(days=ctx.lookback_days)
        page = await calendar.events_page(
            sync_token=sync_token,
            page_token=page_token,
            time_min=time_min,
        )
        events.extend(page.items)
        if not page.next_page_token:
            if not page.next_sync_token:
                raise BookingParseError("Google Calendar response lacked nextSyncToken")
            return events, page.next_sync_token
        page_token = page.next_page_token
    raise BookingParseError("Google Calendar pagination limit exceeded")


def _classify(event: GoogleEvent, cursor: BookingCursor) -> str:
    prior = cursor.events.get(event.id)
    if event.status == "cancelled":
        return "cancelled" if prior else "ignore"
    if not is_handoff_review(event):
        return "ignore"
    if not event.start or not event.start.date_time:
        return "new"
    if prior and prior.start != event.start.date_time:
        return "rescheduled"
    if prior:
        return "ignore"
    return "new"


def _bounded_fingerprints(events: dict[str, CursorEvent]) -> dict[str, CursorEvent]:
    ordered = sorted(events.items(), key=lambda item: item[1].start)
    return dict(ordered[-MAX_CURSOR_EVENTS:])
