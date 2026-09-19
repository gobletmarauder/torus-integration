"""Lead job tests for bounded SQL, write-back, and dry-run safety."""

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

import tis.jobs.lead_sync as lead_sync
from tis.errors import DuplicateWrite
from tis.guards import WriteContext
from tis.http import ControlledClient
from tis.integrations.zoho import ZohoAuth
from tis.jobs.lead_sync import LeadSyncContext, PostgresLeadStore
from tis.mapping.lead_to_zoho import LeadRow, load_field_map

FIELD_MAP = Path(__file__).parents[2] / "config" / "zoho_lead_fields.toml"
LEAD_ID = UUID("00000000-0000-4000-8000-000000000001")


def service_url(host: str) -> str:
    return "https" + f"://{host}"


def lead() -> LeadRow:
    return LeadRow(
        id=LEAD_ID,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        name="Synthetic Lead",
        email="lead@example.com",
        company="Example",
    )


class Audit:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

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
        **_kwargs: Any,
    ) -> None:
        self.rows.append((source, external_id, action, status))


class State:
    async def kill_switch_on(self) -> bool:
        return False


class Store:
    def __init__(self, rows: list[LeadRow]) -> None:
        self.rows = rows
        self.successes: list[tuple[UUID, str]] = []
        self.failures: list[tuple[UUID, str]] = []

    async def pending(self, *, batch_size: int, allow_test: bool) -> list[LeadRow]:
        assert batch_size <= 25
        return self.rows

    async def mark_success(self, lead_id: UUID, zoho_id: str) -> None:
        self.successes.append((lead_id, zoho_id))

    async def mark_failure(self, lead_id: UUID, error: str) -> None:
        self.failures.append((lead_id, error))


def writes(*, dry_run: bool) -> tuple[WriteContext, Audit]:
    audit = Audit()
    return (
        WriteContext(
            dry_run=dry_run,
            state=State(),  # type: ignore[arg-type]
            audit=audit,
            per_run_budgets={("zoho", "upsert_lead"): 25},
            per_day_budgets={("zoho", "upsert_lead"): 200},
        ),
        audit,
    )


def context(store: Store, write_context: WriteContext) -> LeadSyncContext:
    return LeadSyncContext(
        writes=write_context,
        store=store,
        http=ControlledClient(),
        auth=ZohoAuth(
            client_id="synthetic",
            client_secret="synthetic",  # noqa: S106
            refresh_token="synthetic",  # noqa: S106
            accounts_url=service_url("accounts.zoho.com"),
        ),
        field_map=load_field_map(FIELD_MAP),
        api_url=service_url("www.zohoapis.com"),
    )


async def test_dry_run_records_skipped_and_does_not_write_back() -> None:
    store = Store([lead()])
    write_context, audit = writes(dry_run=True)
    ctx = context(store, write_context)
    async with ctx.http:
        result = await lead_sync.run(ctx)
    assert result.skipped == 1
    assert store.successes == []
    assert store.failures == []
    assert audit.rows == [("zoho", str(LEAD_ID), "upsert_lead", "skipped")]


async def test_success_marks_source_row(monkeypatch: pytest.MonkeyPatch) -> None:
    async def succeed(*_args: Any, **_kwargs: Any) -> str:
        return "synthetic-zoho-id"

    monkeypatch.setattr(lead_sync, "upsert_lead", succeed)
    store = Store([lead()])
    write_context, _ = writes(dry_run=False)
    ctx = context(store, write_context)
    try:
        result = await lead_sync.run(ctx)
    finally:
        await ctx.http.aclose()
    assert result.succeeded == 1
    assert store.successes == [(LEAD_ID, "synthetic-zoho-id")]


async def test_duplicate_claim_increments_bounded_source_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def duplicate(*_args: Any, **_kwargs: Any) -> str:
        raise DuplicateWrite("synthetic concurrent claim")

    monkeypatch.setattr(lead_sync, "upsert_lead", duplicate)
    store = Store([lead()])
    write_context, _ = writes(dry_run=False)
    ctx = context(store, write_context)
    try:
        result = await lead_sync.run(ctx)
    finally:
        await ctx.http.aclose()
    assert result.failed == 1
    assert store.failures == [(LEAD_ID, "DuplicateWrite")]


class Database:
    def __init__(self) -> None:
        self.query = ""
        self.parameters: tuple[Any, ...] = ()
        self.executions: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch_all(self, query: str, parameters: tuple[Any, ...]) -> list[Mapping[str, Any]]:
        self.query = query
        self.parameters = parameters
        return [lead().model_dump()]

    async def execute(self, query: str, parameters: tuple[Any, ...]) -> None:
        self.executions.append((query, parameters))


async def test_postgres_store_uses_bounded_skip_locked_query_and_fixed_updates() -> None:
    database = Database()
    store = PostgresLeadStore(database)  # type: ignore[arg-type]
    rows = await store.pending(batch_size=100, allow_test=False)
    assert rows[0].id == LEAD_ID
    assert database.parameters == (False, 25)
    assert "FOR UPDATE SKIP LOCKED" in database.query
    assert "ORDER BY created_at ASC, id ASC" in database.query
    assert str(LEAD_ID) not in database.query
    await store.mark_success(LEAD_ID, "synthetic-zoho-id")
    await store.mark_failure(LEAD_ID, "SyntheticError")
    assert database.executions[0][1] == ("synthetic-zoho-id", LEAD_ID)
    assert database.executions[1][1] == ("SyntheticError", LEAD_ID)
