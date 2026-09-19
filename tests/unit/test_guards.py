"""External-write safety guard tests."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

import pytest

from tis.errors import BudgetExceeded, DuplicateWrite, KillSwitchOn
from tis.guards import PostgresAuditStore, WriteContext, external_write

KEY = ("fixture", "write")


class FakeState:
    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    async def kill_switch_on(self) -> bool:
        return self.enabled


class FakeAudit:
    def __init__(self) -> None:
        self.prior: str | None = None
        self.daily = 0
        self.rows: list[tuple[str, str, str, str, str | None]] = []

    async def status(self, source: str, external_id: str, action: str) -> str | None:
        return self.prior

    async def successful_today(self, source: str, action: str, since: datetime) -> int:
        return self.daily

    async def claim(self, source: str, external_id: str, action: str) -> bool:
        return self.prior != "ok"

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


def context(*, dry_run: bool = False, kill: bool = False) -> tuple[WriteContext, FakeAudit]:
    audit = FakeAudit()
    value = WriteContext(
        dry_run=dry_run,
        state=FakeState(kill),  # type: ignore[arg-type]
        audit=audit,
        per_run_budgets={KEY: 1},
        per_day_budgets={KEY: 2},
    )
    return value, audit


@external_write(source="fixture", action="write", key=lambda external_id, *_args: external_id)
async def guarded(context: WriteContext, external_id: str, calls: list[str]) -> str:
    calls.append(external_id)
    return "ok"


async def test_dry_run_records_skipped_without_calling_wrapped_function() -> None:
    guard_context, audit = context(dry_run=True)
    calls: list[str] = []
    assert await guarded(guard_context, "synthetic-id", calls) is None
    assert calls == []
    assert audit.rows == [("fixture", "synthetic-id", "write", "skipped", None)]


async def test_kill_switch_blocks_and_records_skipped() -> None:
    guard_context, audit = context(kill=True)
    calls: list[str] = []
    with pytest.raises(KillSwitchOn):
        await guarded(guard_context, "synthetic-id", calls)
    assert calls == []
    assert audit.rows[0][3] == "skipped"


async def test_duplicate_success_never_calls_function() -> None:
    guard_context, audit = context()
    audit.prior = "ok"
    calls: list[str] = []
    with pytest.raises(DuplicateWrite):
        await guarded(guard_context, "synthetic-id", calls)
    assert calls == []


async def test_success_records_ok_and_consumes_run_budget() -> None:
    guard_context, audit = context()
    calls: list[str] = []
    assert await guarded(guard_context, "synthetic-id", calls) == "ok"
    assert calls == ["synthetic-id"]
    assert audit.rows[-1][3] == "ok"
    assert guard_context.run_counts[KEY] == 1
    with pytest.raises(BudgetExceeded):
        await guarded(guard_context, "second-id", calls)


async def test_daily_budget_blocks_write() -> None:
    guard_context, audit = context()
    audit.daily = 2
    with pytest.raises(BudgetExceeded):
        await guarded(guard_context, "synthetic-id", [])
    assert audit.rows[-1][3:] == ("error", "BudgetExceeded")


async def test_failure_records_redacted_exception_type_without_success() -> None:
    guard_context, audit = context()

    @external_write(source="fixture", action="write", key=lambda external_id: external_id)
    async def fails(context: WriteContext, external_id: str) -> None:
        raise RuntimeError("personal data must not be stored")

    with pytest.raises(RuntimeError):
        await fails(guard_context, "synthetic-id")
    assert audit.rows[-1] == ("fixture", "synthetic-id", "write", "error", "RuntimeError")
    assert guard_context.run_counts[KEY] == 0


class AuditDatabase:
    def __init__(self) -> None:
        self.row: Mapping[str, Any] | None = None
        self.value: Any = None
        self.executions: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch_one(self, query: str, parameters: tuple[Any, ...]) -> Mapping[str, Any] | None:
        self.executions.append((query, parameters))
        return self.row

    async def fetch_value(self, query: str, parameters: tuple[Any, ...]) -> Any:
        self.executions.append((query, parameters))
        return self.value

    async def execute(self, query: str, parameters: tuple[Any, ...]) -> None:
        self.executions.append((query, parameters))


async def test_postgres_audit_uses_fixed_conflict_key_and_atomic_claim() -> None:
    database = AuditDatabase()
    store = PostgresAuditStore(database)
    database.row = {"id": "synthetic"}
    assert await store.claim("fixture", "synthetic-id", "write") is True
    claim_query, claim_parameters = database.executions[-1]
    assert "ON CONFLICT (source, external_id, action)" in claim_query
    assert "synthetic-id" not in claim_query
    assert claim_parameters == ("fixture", "synthetic-id", "write")
    await store.record("fixture", "synthetic-id", "write", "ok")
    record_query, record_parameters = database.executions[-1]
    assert "ON CONFLICT (source, external_id, action)" in record_query
    assert record_parameters[3] == "ok"


async def test_postgres_audit_rejects_unknown_status() -> None:
    store = PostgresAuditStore(AuditDatabase())
    with pytest.raises(ValueError, match="invalid"):
        await store.record("fixture", "synthetic-id", "write", "pending")
