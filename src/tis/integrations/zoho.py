"""Guarded Zoho OAuth caching and CRM Lead upsert."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC
from typing import Any
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from tis.errors import ExternalError
from tis.guards import WriteContext, external_write
from tis.http import ControlledClient
from tis.mapping.booking_parser import Booking, BookingFieldMap
from tis.mapping.lead_to_zoho import (
    MappedLead,
    ZohoFieldMap,
    map_booking_lead,
)

_ZOHO_STATUSES = frozenset({400, 401, 429, 500, 502, 503, 504})


class ZohoDataError(ExternalError):
    """Zoho rejected a mapped lead as invalid or conflicting."""


class TokenResponse(BaseModel):
    """Validated subset of an OAuth refresh response."""

    model_config = ConfigDict(extra="ignore")

    access_token: SecretStr
    expires_in: int = Field(gt=300)


class UpsertDetails(BaseModel):
    """Validated subset of Zoho result details."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None


class UpsertItem(BaseModel):
    """Validated single-record Zoho upsert result."""

    model_config = ConfigDict(extra="ignore")

    status: str
    code: str
    details: UpsertDetails = Field(default_factory=UpsertDetails)


class UpsertResponse(BaseModel):
    """Validated Zoho upsert response envelope."""

    model_config = ConfigDict(extra="ignore")

    data: list[UpsertItem]


class SearchRecord(BaseModel):
    """Validated minimal Zoho record returned by search and related-list reads."""

    model_config = ConfigDict(extra="ignore")

    id: str
    note_content: str | None = Field(default=None, alias="Note_Content")
    description: str | None = Field(default=None, alias="Description")


class SearchResponse(BaseModel):
    """Validated Zoho record-list envelope."""

    model_config = ConfigDict(extra="ignore")

    data: list[SearchRecord] = Field(default_factory=list)


class BookingSyncResult(BaseModel):
    """Non-personal result of one guarded booking workflow."""

    module: str
    record_id: str
    created_lead: bool


class ZohoAuth:
    """Cache one access token in memory and refresh it five minutes early."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        accounts_url: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._accounts_url = accounts_url.rstrip("/")
        self._clock = clock
        self._cached: tuple[str, float] | None = None
        self._lock = asyncio.Lock()

    async def token(self, http: ControlledClient, *, force: bool = False) -> str:
        """Return a cached token or perform one OAuth refresh request."""
        async with self._lock:
            if not force and self._cached and self._cached[1] > self._clock():
                return self._cached[0]
            response = await http.request(
                "POST",
                f"{self._accounts_url}/oauth/v2/token",
                data={
                    "refresh_token": self._refresh_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "refresh_token",
                },
            )
            try:
                token = TokenResponse.model_validate(response.json())
            except (ValueError, ValidationError) as error:
                raise ExternalError("Zoho token response was invalid") from error
            value = token.access_token.get_secret_value()
            self._cached = (value, self._clock() + token.expires_in - 300)
            return value


def _lead_key(lead: MappedLead, *_args: Any, **_kwargs: Any) -> str:
    return str(lead.supabase_lead_id)


def _booking_key(booking: Booking, *_args: Any, **_kwargs: Any) -> str:
    return booking.event_id


@external_write(source="zoho", action="upsert_lead", key=_lead_key)
async def upsert_lead(
    context: WriteContext,
    lead: MappedLead,
    http: ControlledClient,
    auth: ZohoAuth,
    *,
    api_url: str,
    api_version: str = "v8",
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> str:
    """Upsert one Zoho Lead; this performs one guarded external business write."""
    token = await auth.token(http)
    refreshed = False
    for attempt in range(3):
        response = await http.request(
            "POST",
            f"{api_url.rstrip('/')}/crm/{api_version}/Leads/upsert",
            headers={"Authorization": f"Zoho-oauthtoken {token}"},
            json={
                "data": [lead.fields],
                "duplicate_check_fields": [lead.duplicate_field],
                "trigger": ["workflow"],
            },
            accepted_statuses=_ZOHO_STATUSES,
        )
        code = _response_code(response)
        if response.status_code == 401 or code in {"INVALID_TOKEN", "INVALID_OAUTHTOKEN"}:
            if refreshed:
                raise ExternalError("Zoho rejected the refreshed access token")
            token = await auth.token(http, force=True)
            refreshed = True
            continue
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == 2:
                raise ExternalError("Zoho retry budget exhausted")
            await sleep(_retry_delay(response.headers.get("retry-after"), attempt))
            continue
        return _parse_upsert(response.json())
    raise ExternalError("Zoho upsert failed")


@external_write(source="google_calendar", action="sync_booking", key=_booking_key)
async def sync_booking(
    context: WriteContext,
    booking: Booking,
    field_map: ZohoFieldMap,
    booking_fields: BookingFieldMap,
    http: ControlledClient,
    auth: ZohoAuth,
    *,
    api_url: str,
    api_version: str = "v8",
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> BookingSyncResult:
    """Match or create a CRM record; this performs guarded Zoho business writes."""
    base = f"{api_url.rstrip('/')}/crm/{api_version}"
    contact = await _search_by_email(http, auth, base, "Contacts", booking.attendee_email)
    lead = (
        None
        if contact
        else await _search_by_email(http, auth, base, "Leads", booking.attendee_email)
    )
    match = contact or lead
    if not match:
        mapped = map_booking_lead(booking, field_map, booking_fields)
        response = await _authorized_request(
            http,
            auth,
            "POST",
            f"{base}/Leads/upsert",
            json={
                "data": [mapped.fields],
                "duplicate_check_fields": [mapped.duplicate_field],
                "trigger": ["workflow"],
            },
            sleep=sleep,
        )
        return BookingSyncResult(
            module="Leads",
            record_id=_parse_upsert(response.json()),
            created_lead=True,
        )

    module = "Contacts" if contact else "Leads"
    marker = f"Google Calendar event: {booking.event_id}"
    note_exists = await _related_contains(http, auth, base, module, match.id, "Notes", marker)
    task_exists = await _related_contains(http, auth, base, module, match.id, "Tasks", marker)
    timestamp = booking.start.astimezone(UTC).isoformat().replace("+00:00", "Z")
    update = await _authorized_request(
        http,
        auth,
        "PUT",
        f"{base}/{module}/{match.id}",
        json={"data": [{booking_fields.booking_timestamp: timestamp}]},
        sleep=sleep,
    )
    _parse_write(update.json())
    if not note_exists:
        note = await _authorized_request(
            http,
            auth,
            "POST",
            f"{base}/Notes",
            json={
                "data": [
                    {
                        booking_fields.note_parent: {
                            "module": {"api_name": module},
                            "id": match.id,
                        },
                        booking_fields.note_title: booking_fields.note_title_value,
                        booking_fields.note_content: (
                            f"{booking_fields.note_title_value}\n{marker}"
                        ),
                    }
                ]
            },
            sleep=sleep,
        )
        _parse_write(note.json())
    if not task_exists:
        task = await _authorized_request(
            http,
            auth,
            "POST",
            f"{base}/Tasks",
            json={
                "data": [
                    {
                        booking_fields.task_who: {"id": match.id},
                        "$se_module": module,
                        booking_fields.task_subject: booking_fields.task_subject_value,
                        booking_fields.task_description: marker,
                        booking_fields.task_due_date: booking.start.date().isoformat(),
                        booking_fields.task_status: booking_fields.task_status_value,
                    }
                ]
            },
            sleep=sleep,
        )
        _parse_write(task.json())
    return BookingSyncResult(module=module, record_id=match.id, created_lead=False)


async def _search_by_email(
    http: ControlledClient,
    auth: ZohoAuth,
    base: str,
    module: str,
    email: str,
) -> SearchRecord | None:
    query = urlencode({"email": email})
    response = await _authorized_request(
        http,
        auth,
        "GET",
        f"{base}/{module}/search?{query}",
        accepted_statuses=frozenset({204}),
    )
    if response.status_code == 204:
        return None
    parsed = _parse_search(response.json())
    return parsed[0] if parsed else None


async def _related_contains(
    http: ControlledClient,
    auth: ZohoAuth,
    base: str,
    module: str,
    record_id: str,
    related: str,
    marker: str,
) -> bool:
    response = await _authorized_request(
        http,
        auth,
        "GET",
        f"{base}/{module}/{record_id}/{related}",
        accepted_statuses=frozenset({204}),
    )
    if response.status_code == 204:
        return False
    for record in _parse_search(response.json()):
        if marker in (record.note_content or "") or marker in (record.description or ""):
            return True
    return False


async def _authorized_request(
    http: ControlledClient,
    auth: ZohoAuth,
    method: str,
    url: str,
    *,
    json: Any = None,
    accepted_statuses: frozenset[int] = frozenset(),
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Any:
    """Send a Zoho request for an already-guarded workflow with bounded recovery."""
    token = await auth.token(http)
    refreshed = False
    for attempt in range(3):
        response = await http.request(
            method,
            url,
            headers={"Authorization": f"Zoho-oauthtoken {token}"},
            json=json,
            accepted_statuses=_ZOHO_STATUSES | accepted_statuses,
        )
        code = _response_code(response)
        if response.status_code == 401 or code in {"INVALID_TOKEN", "INVALID_OAUTHTOKEN"}:
            if refreshed:
                raise ExternalError("Zoho rejected the refreshed access token")
            token = await auth.token(http, force=True)
            refreshed = True
            continue
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == 2:
                raise ExternalError("Zoho retry budget exhausted")
            await sleep(_retry_delay(response.headers.get("retry-after"), attempt))
            continue
        return response
    raise ExternalError("Zoho request failed")


def _response_code(response: Any) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    if isinstance(body, dict):
        if isinstance(body.get("code"), str):
            return str(body["code"])
        data = body.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return str(data[0].get("code", ""))
    return ""


def _parse_upsert(body: Any) -> str:
    try:
        parsed = UpsertResponse.model_validate(body)
    except ValidationError as error:
        raise ExternalError("Zoho upsert response was invalid") from error
    if len(parsed.data) != 1:
        raise ExternalError("Zoho upsert response had an unexpected record count")
    item = parsed.data[0]
    if item.status != "success" or not item.details.id:
        if item.code in {"INVALID_DATA", "DUPLICATE_DATA", "MANDATORY_NOT_FOUND"}:
            raise ZohoDataError("Zoho rejected the mapped lead")
        raise ExternalError("Zoho upsert returned an error")
    return item.details.id


def _parse_write(body: Any) -> str:
    return _parse_upsert(body)


def _parse_search(body: Any) -> list[SearchRecord]:
    try:
        return SearchResponse.model_validate(body).data
    except ValidationError as error:
        raise ExternalError("Zoho search response was invalid") from error


def _retry_delay(value: str | None, attempt: int) -> float:
    if value and value.isdigit():
        return float(min(int(value), 5))
    return float(min(0.25 * (2**attempt), 1.0))
