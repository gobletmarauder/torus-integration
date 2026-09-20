"""Zoho adapter tests with intercepted synthetic HTTP only."""

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from respx import MockResponse

from tis.errors import ExternalError, KillSwitchOn
from tis.guards import WriteContext
from tis.http import ControlledClient
from tis.integrations.zoho import ZohoAuth, ZohoDataError, sync_booking, upsert_lead
from tis.mapping.booking_parser import Booking, load_booking_field_map
from tis.mapping.lead_to_zoho import MappedLead, load_field_map

ACCOUNTS = "https" + "://accounts.zoho.com"
API = "https" + "://www.zohoapis.com"
LEAD_ID = UUID("00000000-0000-4000-8000-000000000001")
ROOT = Path(__file__).parents[2]


class State:
    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    async def kill_switch_on(self) -> bool:
        return self.enabled


class Audit:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str, str | None]] = []

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
        self.rows.append((source, external_id, action, status, error))


def write_context(*, dry_run: bool = False, kill: bool = False) -> tuple[WriteContext, Audit]:
    audit = Audit()
    context = WriteContext(
        dry_run=dry_run,
        state=State(kill),  # type: ignore[arg-type]
        audit=audit,
        per_run_budgets={
            ("zoho", "upsert_lead"): 25,
            ("google_calendar", "sync_booking"): 10,
        },
        per_day_budgets={
            ("zoho", "upsert_lead"): 200,
            ("google_calendar", "sync_booking"): 100,
        },
    )
    return context, audit


def mapped_lead() -> MappedLead:
    return MappedLead(
        supabase_lead_id=LEAD_ID,
        duplicate_field="supabase_lead_id",
        fields={
            "supabase_lead_id": str(LEAD_ID),
            "Last_Name": "Example",
            "Email": "lead@example.com",
            "Company": "Example",
        },
    )


def auth() -> ZohoAuth:
    return ZohoAuth(
        client_id="synthetic-client",
        client_secret="synthetic-secret",  # noqa: S106
        refresh_token="synthetic-refresh",  # noqa: S106
        accounts_url=ACCOUNTS,
    )


async def test_guarded_upsert_refreshes_and_records_success(respx_mock: object) -> None:
    token = respx_mock.post(f"{ACCOUNTS}/oauth/v2/token").mock(  # type: ignore[attr-defined]
        return_value=MockResponse(200, json={"access_token": "synthetic-token", "expires_in": 3600})
    )
    crm = respx_mock.post(f"{API}/crm/v8/Leads/upsert").mock(  # type: ignore[attr-defined]
        return_value=MockResponse(
            200,
            json={
                "data": [
                    {
                        "status": "success",
                        "code": "SUCCESS",
                        "details": {"id": "synthetic-zoho-id"},
                    }
                ]
            },
        )
    )
    context, audit = write_context()
    async with ControlledClient() as http:
        result = await upsert_lead(context, mapped_lead(), http, auth(), api_url=API)
    assert result == "synthetic-zoho-id"
    assert token.call_count == 1
    assert crm.call_count == 1
    body = crm.calls.last.request.content.decode()
    assert '"duplicate_check_fields":["supabase_lead_id"]' in body
    assert audit.rows[-1][:4] == ("zoho", str(LEAD_ID), "upsert_lead", "ok")


async def test_dry_run_records_intent_with_zero_http(respx_mock: object) -> None:
    context, audit = write_context(dry_run=True)
    async with ControlledClient() as http:
        result = await upsert_lead(context, mapped_lead(), http, auth(), api_url=API)
    assert result is None
    assert not respx_mock.calls  # type: ignore[attr-defined]
    assert audit.rows == [("zoho", str(LEAD_ID), "upsert_lead", "skipped", None)]


async def test_invalid_token_refreshes_once(respx_mock: object) -> None:
    token = respx_mock.post(f"{ACCOUNTS}/oauth/v2/token").mock(  # type: ignore[attr-defined]
        side_effect=[
            MockResponse(200, json={"access_token": "first", "expires_in": 3600}),
            MockResponse(200, json={"access_token": "second", "expires_in": 3600}),
        ]
    )
    crm = respx_mock.post(f"{API}/crm/v8/Leads/upsert").mock(  # type: ignore[attr-defined]
        side_effect=[
            MockResponse(401, json={"code": "INVALID_TOKEN"}),
            MockResponse(
                200,
                json={
                    "data": [
                        {
                            "status": "success",
                            "code": "SUCCESS",
                            "details": {"id": "synthetic-zoho-id"},
                        }
                    ]
                },
            ),
        ]
    )
    context, _ = write_context()
    async with ControlledClient() as http:
        await upsert_lead(context, mapped_lead(), http, auth(), api_url=API)
    assert token.call_count == 2
    assert crm.call_count == 2


@pytest.mark.parametrize("code", ["INVALID_DATA", "DUPLICATE_DATA"])
async def test_data_errors_are_typed(respx_mock: object, code: str) -> None:
    respx_mock.post(f"{ACCOUNTS}/oauth/v2/token").mock(  # type: ignore[attr-defined]
        return_value=MockResponse(200, json={"access_token": "token", "expires_in": 3600})
    )
    respx_mock.post(f"{API}/crm/v8/Leads/upsert").mock(  # type: ignore[attr-defined]
        return_value=MockResponse(
            400, json={"data": [{"status": "error", "code": code, "details": {}}]}
        )
    )
    context, audit = write_context()
    async with ControlledClient() as http:
        with pytest.raises(ZohoDataError):
            await upsert_lead(context, mapped_lead(), http, auth(), api_url=API)
    assert audit.rows[-1][4] == "ZohoDataError"


async def test_rate_limit_retries_are_bounded(respx_mock: object) -> None:
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    respx_mock.post(f"{ACCOUNTS}/oauth/v2/token").mock(  # type: ignore[attr-defined]
        return_value=MockResponse(200, json={"access_token": "token", "expires_in": 3600})
    )
    crm = respx_mock.post(f"{API}/crm/v8/Leads/upsert").mock(  # type: ignore[attr-defined]
        side_effect=[MockResponse(429, headers={"retry-after": "1"})] * 3
    )
    context, _ = write_context()
    async with ControlledClient() as http:
        with pytest.raises(ExternalError, match="retry budget"):
            await upsert_lead(context, mapped_lead(), http, auth(), api_url=API, sleep=sleep)
    assert crm.call_count == 3
    assert sleeps == [1.0, 1.0]


def booking() -> Booking:
    return Booking(
        event_id="synthetic-event",
        start=datetime.fromisoformat("2026-01-20T16:00:00+00:00"),
        end=datetime.fromisoformat("2026-01-20T16:30:00+00:00"),
        attendee_email="prospect@example.com",
        attendee_name="Example Person",
    )


async def test_booking_dry_run_records_exact_key_with_zero_http(respx_mock: object) -> None:
    context, audit = write_context(dry_run=True)
    async with ControlledClient() as http:
        result = await sync_booking(
            context,
            booking(),
            load_field_map(ROOT / "config/zoho_lead_fields.toml"),
            load_booking_field_map(ROOT / "config/zoho_booking_fields.toml"),
            http,
            auth(),
            api_url=API,
        )
    assert result is None
    assert not respx_mock.calls  # type: ignore[attr-defined]
    assert audit.rows[-1][:4] == (
        "google_calendar",
        "synthetic-event",
        "sync_booking",
        "skipped",
    )


async def test_booking_kill_switch_blocks_before_http(respx_mock: object) -> None:
    context, audit = write_context(kill=True)
    async with ControlledClient() as http:
        with pytest.raises(KillSwitchOn):
            await sync_booking(
                context,
                booking(),
                load_field_map(ROOT / "config/zoho_lead_fields.toml"),
                load_booking_field_map(ROOT / "config/zoho_booking_fields.toml"),
                http,
                auth(),
                api_url=API,
            )
    assert not respx_mock.calls  # type: ignore[attr-defined]
    assert audit.rows[-1][:4] == (
        "google_calendar",
        "synthetic-event",
        "sync_booking",
        "skipped",
    )


async def test_booking_prefers_contact_and_creates_note_task_and_timestamp(
    respx_mock: object,
) -> None:
    respx_mock.post(f"{ACCOUNTS}/oauth/v2/token").mock(  # type: ignore[attr-defined]
        return_value=MockResponse(200, json={"access_token": "token", "expires_in": 3600})
    )
    base = f"{API}/crm/v8"
    contact = respx_mock.get(url__regex=rf"{base}/Contacts/search.*").mock(  # type: ignore[attr-defined]
        return_value=MockResponse(200, json={"data": [{"id": "contact-1"}]})
    )
    related = respx_mock.get(url__regex=rf"{base}/Contacts/contact-1/(Notes|Tasks)").mock(  # type: ignore[attr-defined]
        return_value=MockResponse(204)
    )
    response = {
        "data": [{"status": "success", "code": "SUCCESS", "details": {"id": "synthetic-id"}}]
    }
    update = respx_mock.put(f"{base}/Contacts/contact-1").mock(  # type: ignore[attr-defined]
        return_value=MockResponse(200, json=response)
    )
    note = respx_mock.post(f"{base}/Notes").mock(  # type: ignore[attr-defined]
        return_value=MockResponse(201, json=response)
    )
    task = respx_mock.post(f"{base}/Tasks").mock(  # type: ignore[attr-defined]
        return_value=MockResponse(201, json=response)
    )
    context, audit = write_context()
    async with ControlledClient() as http:
        result = await sync_booking(
            context,
            booking(),
            load_field_map(ROOT / "config/zoho_lead_fields.toml"),
            load_booking_field_map(ROOT / "config/zoho_booking_fields.toml"),
            http,
            auth(),
            api_url=API,
        )
    assert result.module == "Contacts" and not result.created_lead
    assert contact.called and related.call_count == 2
    assert update.called and note.called and task.called
    assert b'"Status":"Not started"' in task.calls.last.request.content
    assert audit.rows[-1][:4] == (
        "google_calendar",
        "synthetic-event",
        "sync_booking",
        "ok",
    )


async def test_booking_without_match_email_upserts_lead(respx_mock: object) -> None:
    respx_mock.post(f"{ACCOUNTS}/oauth/v2/token").mock(  # type: ignore[attr-defined]
        return_value=MockResponse(200, json={"access_token": "token", "expires_in": 3600})
    )
    base = f"{API}/crm/v8"
    searches = respx_mock.get(url__regex=rf"{base}/(Contacts|Leads)/search.*").mock(  # type: ignore[attr-defined]
        return_value=MockResponse(204)
    )
    upsert = respx_mock.post(f"{base}/Leads/upsert").mock(  # type: ignore[attr-defined]
        return_value=MockResponse(
            200,
            json={"data": [{"status": "success", "code": "SUCCESS", "details": {"id": "lead-1"}}]},
        )
    )
    context, _ = write_context()
    async with ControlledClient() as http:
        result = await sync_booking(
            context,
            booking(),
            load_field_map(ROOT / "config/zoho_lead_fields.toml"),
            load_booking_field_map(ROOT / "config/zoho_booking_fields.toml"),
            http,
            auth(),
            api_url=API,
        )
    assert searches.call_count == 2
    assert result.created_lead and result.record_id == "lead-1"
    body = upsert.calls.last.request.content
    assert b'"duplicate_check_fields":["Email"]' in body
    assert b'"Handoff_Review_Booked_At"' in body
