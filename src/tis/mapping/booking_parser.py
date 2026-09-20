"""Parse redacted Google Handoff Review events into typed booking data."""

from __future__ import annotations

import html
import re
import tomllib
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

from tis.errors import ExternalError
from tis.integrations.google_calendar import GoogleEvent, GooglePerson

_TAG = re.compile(r"<[^>]+>")
_SUMMARY_NAME = re.compile(r"^Handoff Review(?:\s*\((?P<name>[^)]+)\))?$")
_API_NAME = re.compile(r"^[A-Za-z$][A-Za-z0-9_$]*$")


class BookingParseError(ExternalError):
    """A Handoff Review event lacked required safe booking data."""


class Booking(BaseModel):
    """Validated internal booking data; never log instances of this model."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    start: datetime
    end: datetime
    attendee_email: str
    attendee_name: str | None = None
    phone: str | None = None


class BookingFieldMap(BaseModel):
    """Closed Zoho booking field names and safe configured literals."""

    model_config = ConfigDict(extra="forbid")

    booking_timestamp: str
    note_parent: str
    note_title: str
    note_content: str
    task_who: str
    task_subject: str
    task_description: str
    task_due_date: str
    task_status: str
    note_title_value: str
    task_subject_value: str
    task_status_value: str
    individual_company: str
    personal_email_domains: frozenset[str]

    @field_validator(
        "booking_timestamp",
        "note_parent",
        "note_title",
        "note_content",
        "task_who",
        "task_subject",
        "task_description",
        "task_due_date",
        "task_status",
    )
    @classmethod
    def validate_api_name(cls, value: str) -> str:
        """Reject values that are not literal Zoho API field names."""
        if not _API_NAME.fullmatch(value):
            raise ValueError("invalid Zoho booking field API name")
        return value

    @field_validator("personal_email_domains")
    @classmethod
    def validate_domains(cls, value: frozenset[str]) -> frozenset[str]:
        """Require lowercase exact domains without wildcard semantics."""
        if not value or any(domain != domain.lower() or "*" in domain for domain in value):
            raise ValueError("personal email domains must be exact lowercase values")
        return value


def load_booking_field_map(path: Path) -> BookingFieldMap:
    """Load non-secret booking field names and safe literals from TOML."""
    with path.open("rb") as handle:
        document = tomllib.load(handle)
    fields = document.get("fields", {})
    values = document.get("values", {})
    return BookingFieldMap(
        **fields,
        note_title_value=values.get("note_title"),
        task_subject_value=values.get("task_subject"),
        task_status_value=values.get("task_status"),
        individual_company=values.get("individual_company"),
        personal_email_domains=frozenset(values.get("personal_email_domains", [])),
    )


def is_handoff_review(event: GoogleEvent) -> bool:
    """Return whether an event uses the captured Handoff Review title shape."""
    return _SUMMARY_NAME.fullmatch(" ".join(event.summary.split())) is not None


def parse_booking(event: GoogleEvent) -> Booking:
    """Parse one confirmed Handoff Review event without external side effects."""
    if not is_handoff_review(event):
        raise BookingParseError("event was not a Handoff Review booking")
    if event.status != "confirmed":
        raise BookingParseError("booking event was not confirmed")
    if not event.start or not event.start.date_time or not event.end or not event.end.date_time:
        raise BookingParseError("booking event did not contain timed boundaries")
    attendee = _attendee(event.attendees, event.organizer)
    if not attendee.email or "@" not in attendee.email:
        raise BookingParseError("booking attendee email was missing")
    description_name, phone = _description_answers(event.description)
    summary_match = _SUMMARY_NAME.fullmatch(" ".join(event.summary.split()))
    summary_name = summary_match.group("name") if summary_match else None
    return Booking(
        event_id=event.id,
        start=event.start.date_time,
        end=event.end.date_time,
        attendee_email=attendee.email.strip().lower(),
        attendee_name=attendee.display_name or summary_name or description_name,
        phone=phone,
    )


def is_personal_email(email: str, field_map: BookingFieldMap) -> bool:
    """Classify only exact configured personal-email domains."""
    _, separator, domain = email.strip().lower().partition("@")
    return bool(separator and domain in field_map.personal_email_domains)


def _attendee(attendees: list[GooglePerson], organizer: GooglePerson | None) -> GooglePerson:
    organizer_email = (organizer.email or "").lower() if organizer else ""
    candidates = [
        attendee
        for attendee in attendees
        if attendee.email
        and not attendee.self_
        and not attendee.organizer
        and attendee.email.lower() != organizer_email
    ]
    if not candidates:
        raise BookingParseError("booking attendee was missing")
    return sorted(candidates, key=lambda value: (value.email or "").lower())[0]


def _description_answers(description: str) -> tuple[str | None, str | None]:
    plain = html.unescape(_TAG.sub("", description))
    lines = [line.strip() for line in plain.splitlines() if line.strip()]
    if lines and lines[0].lower() == "booked by":
        lines = lines[1:]
    name = next((line for line in lines if "@" not in line and not _looks_like_phone(line)), None)
    phone = next((line for line in lines if _looks_like_phone(line)), None)
    return name, phone


def _looks_like_phone(value: str) -> bool:
    digits = "".join(character for character in value if character.isdigit())
    return 7 <= len(digits) <= 15
