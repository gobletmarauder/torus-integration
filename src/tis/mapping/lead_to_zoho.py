"""Validated, deterministic mapping from Supabase leads to Zoho API fields."""

from __future__ import annotations

import re
import tomllib
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tis.mapping.booking_parser import Booking, BookingFieldMap, is_personal_email

_API_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class LeadRow(BaseModel):
    """One synthetic-safe representation of the authoritative leads contract."""

    model_config = ConfigDict(extra="ignore")

    id: UUID
    created_at: datetime
    name: str
    email: str
    company: str | None = None
    headcount_band: str | None = None
    systems_named: str | None = None
    calculator_annual_estimate: Decimal | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None
    referrer: str | None = None
    page_path: str | None = None
    crm_synced: bool = False
    crm_sync_attempts: int = 0
    crm_last_error: str | None = None
    is_test: bool = False


class ZohoFieldMap(BaseModel):
    """Closed set of non-secret Zoho Lead API names and configured values."""

    model_config = ConfigDict(extra="forbid")

    supabase_lead_id: str
    first_name: str
    last_name: str
    email: str
    company: str
    description: str
    lead_source: str
    lead_source_value: str | None = Field(default=None)

    @field_validator(
        "supabase_lead_id",
        "first_name",
        "last_name",
        "email",
        "company",
        "description",
        "lead_source",
    )
    @classmethod
    def validate_api_name(cls, value: str) -> str:
        """Reject values that are not literal Zoho field API names."""
        if not _API_NAME.fullmatch(value):
            raise ValueError("invalid Zoho field API name")
        return value


class MappedLead(BaseModel):
    """Outgoing fields plus the internal idempotency identifier."""

    supabase_lead_id: UUID
    fields: dict[str, str | Decimal]
    duplicate_field: str


class MappedBookingLead(BaseModel):
    """Outgoing Lead fields derived from a Calendar booking."""

    fields: dict[str, str | Decimal]
    duplicate_field: str


def load_field_map(path: Path) -> ZohoFieldMap:
    """Load non-secret API names from a local TOML file; this reads no environment values."""
    with path.open("rb") as handle:
        document = tomllib.load(handle)
    fields = document.get("fields", {})
    values = document.get("values", {})
    mapping = ZohoFieldMap(**fields, lead_source_value=values.get("lead_source"))
    api_names = [
        mapping.supabase_lead_id,
        mapping.first_name,
        mapping.last_name,
        mapping.email,
        mapping.company,
        mapping.description,
        mapping.lead_source,
    ]
    if len(api_names) != len(set(api_names)):
        raise ValueError("Zoho field API names must be unique")
    return mapping


def map_lead(lead: LeadRow, mapping: ZohoFieldMap) -> MappedLead:
    """Build the only payload fields permitted to leave the service."""
    first_name, last_name = _split_name(lead.name)
    fields: dict[str, str | Decimal] = {
        mapping.supabase_lead_id: str(lead.id),
        mapping.last_name: last_name,
        mapping.email: lead.email,
        mapping.company: _company(lead),
    }
    if first_name:
        fields[mapping.first_name] = first_name
    description = _description(lead)
    if description:
        fields[mapping.description] = description
    if mapping.lead_source_value:
        fields[mapping.lead_source] = mapping.lead_source_value
    return MappedLead(
        supabase_lead_id=lead.id,
        fields=fields,
        duplicate_field=mapping.supabase_lead_id,
    )


def map_booking_lead(
    booking: Booking,
    mapping: ZohoFieldMap,
    booking_fields: BookingFieldMap,
) -> MappedBookingLead:
    """Build a booking-origin Lead payload without inventing a Supabase identifier."""
    first_name, last_name = _split_name(booking.attendee_name or "")
    _, _, domain = booking.attendee_email.partition("@")
    company = (
        booking_fields.individual_company
        if is_personal_email(booking.attendee_email, booking_fields)
        else domain
    )
    fields: dict[str, str | Decimal] = {
        mapping.last_name: last_name,
        mapping.email: booking.attendee_email,
        mapping.company: company or booking_fields.individual_company,
        booking_fields.booking_timestamp: booking.start.isoformat(),
    }
    if first_name:
        fields[mapping.first_name] = first_name
    if mapping.lead_source_value:
        fields[mapping.lead_source] = mapping.lead_source_value
    return MappedBookingLead(fields=fields, duplicate_field=mapping.email)


def _split_name(name: str) -> tuple[str | None, str]:
    cleaned = " ".join(name.split())
    first, separator, remainder = cleaned.partition(" ")
    if not separator:
        return None, first or "Unknown"
    return first, remainder


def _company(lead: LeadRow) -> str:
    company = (lead.company or "").strip()
    if company:
        return company
    _, separator, domain = lead.email.strip().lower().partition("@")
    return domain if separator and domain else "Unknown"


def _description(lead: LeadRow) -> str:
    values: list[tuple[str, Any]] = [
        ("Headcount band", lead.headcount_band),
        ("Systems named", lead.systems_named),
        ("Annual estimate", lead.calculator_annual_estimate),
        ("Page path", lead.page_path),
        ("UTM source", lead.utm_source),
        ("UTM medium", lead.utm_medium),
        ("UTM campaign", lead.utm_campaign),
        ("UTM content", lead.utm_content),
        ("UTM term", lead.utm_term),
    ]
    return "\n".join(f"{label}: {value}" for label, value in values if value not in (None, ""))
