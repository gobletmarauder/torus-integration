"""Database-only keepalive tests."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import HttpUrl
from respx import MockResponse

from tis.errors import KillSwitchOn
from tis.guards import WriteContext
from tis.http import ControlledClient
from tis.jobs.keepalive import KeepaliveContext, run

NOW = datetime(2026, 1, 2, tzinfo=UTC)
URL = "https" + "://uptime.betterstack.com/synthetic-keepalive"


class Database:
    def __init__(self, *, fail: bool = False) -> None:
        self.queries: list[tuple[str, Sequence[Any]]] = []
        self.fail = fail

    async def fetch_value(self, query: str, parameters: Sequence[Any]) -> Any:
        self.queries.append((query, parameters))
        if self.fail:
            raise RuntimeError("synthetic database failure")
        return 1


class State:
    def __init__(self, kill: bool = False) -> None:
        self.kill = kill

    async def kill_switch_on(self) -> bool:
        return self.kill


class Audit:
    def __init__(self) -> None:
        self.rows: list[str] = []

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
        self.rows.append(status)


def writes(*, dry_run: bool = True, kill: bool = False) -> tuple[WriteContext, Audit]:
    audit = Audit()
    return (
        WriteContext(
            dry_run=dry_run,
            state=State(kill),  # type: ignore[arg-type]
            audit=audit,
            per_run_budgets={("betterstack", "heartbeat"): 10},
            per_day_budgets={("betterstack", "heartbeat"): 400},
        ),
        audit,
    )


async def test_dry_run_selects_once_and_skips_http() -> None:
    database = Database()
    context, audit = writes()
    async with ControlledClient() as http:
        result = await run(
            KeepaliveContext(database, context, http, HttpUrl(URL), clock=lambda: NOW)  # type: ignore[arg-type]
        )
    assert database.queries == [("SELECT 1", ())]
    assert result.skipped == 1 and result.failed == 0
    assert audit.rows == ["skipped"]


async def test_live_keepalive_heartbeats_after_database_success(respx_mock: object) -> None:
    database = Database()
    context, audit = writes(dry_run=False)
    route = respx_mock.get(URL).mock(return_value=MockResponse(200))  # type: ignore[attr-defined]
    async with ControlledClient() as http:
        result = await run(
            KeepaliveContext(database, context, http, HttpUrl(URL), clock=lambda: NOW)  # type: ignore[arg-type]
        )
    assert route.called
    assert result.succeeded == 1
    assert audit.rows == ["ok"]


async def test_database_error_prevents_heartbeat() -> None:
    context, audit = writes(dry_run=False)
    async with ControlledClient() as http:
        with pytest.raises(RuntimeError, match="database"):
            await run(
                KeepaliveContext(Database(fail=True), context, http, HttpUrl(URL))  # type: ignore[arg-type]
            )
    assert audit.rows == []


async def test_kill_switch_records_skipped_after_harmless_read() -> None:
    database = Database()
    context, audit = writes(kill=True)
    async with ControlledClient() as http:
        with pytest.raises(KillSwitchOn):
            await run(KeepaliveContext(database, context, http, HttpUrl(URL)))  # type: ignore[arg-type]
    assert len(database.queries) == 1
    assert audit.rows == ["skipped"]
