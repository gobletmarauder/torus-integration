"""Booking parsing tests using only synthetic identities."""

import json
from pathlib import Path

import pytest

from tis.integrations.google_calendar import GoogleEvent, GooglePerson
from tis.mapping.booking_parser import (
    BookingParseError,
    is_handoff_review,
    is_personal_email,
    load_booking_field_map,
    parse_booking,
)

ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "tests/fixtures/google_calendar/handoff-review-redacted.json"
FIELD_MAP = ROOT / "config/zoho_booking_fields.toml"


def captured_event() -> GoogleEvent:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return GoogleEvent.model_validate(document)


def test_captured_shape_parses_and_missing_answers_are_optional() -> None:
    event = captured_event()
    booking = parse_booking(event)
    assert booking.event_id == "synthetic-handoff-event-001"
    assert booking.attendee_email == "prospect@example.com"
    assert booking.attendee_name == "Example Person"
    assert booking.phone == "+1 202-555-0100"
    assert is_handoff_review(event)
    event.description = ""
    assert parse_booking(event).phone is None


def test_attendee_selection_is_deterministic() -> None:
    event = captured_event()
    event.attendees.insert(0, GooglePerson(email="zeta@example.com"))
    event.attendees.insert(0, GooglePerson(email="alpha@example.com"))
    assert parse_booking(event).attendee_email == "alpha@example.com"


def test_missing_attendee_and_cancelled_events_are_rejected() -> None:
    event = captured_event()
    event.attendees = [event.attendees[-1]]
    with pytest.raises(BookingParseError, match="attendee"):
        parse_booking(event)
    event = captured_event()
    event.status = "cancelled"
    with pytest.raises(BookingParseError, match="confirmed"):
        parse_booking(event)


def test_closed_personal_domain_classification() -> None:
    fields = load_booking_field_map(FIELD_MAP)
    assert is_personal_email("person@gmail.com", fields)
    assert not is_personal_email("person@business.example", fields)


def test_non_handoff_title_is_rejected() -> None:
    event = captured_event()
    event.summary = "Unrelated meeting"
    assert not is_handoff_review(event)
    with pytest.raises(BookingParseError, match="not a Handoff"):
        parse_booking(event)
