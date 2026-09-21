"""Fail-closed host-health tests."""

from collections import namedtuple
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import HttpUrl
from respx import MockResponse

from tis.guards import WriteContext
from tis.http import ControlledClient
from tis.jobs.host_health import HostHealthContext, run

NOW = datetime(2026, 1, 2, 12, tzinfo=UTC)
URL = "https" + "://uptime.betterstack.com/synthetic-health"
Usage = namedtuple("Usage", "total used free")


class Database:
    def __init__(self, aged: int = 0, errors: int = 0) -> None:
        self.aged = aged
        self.errors = errors

    async def fetch_value(self, query: str, parameters: Sequence[Any]) -> Any:
        return self.errors if "integration_log" in query else self.aged


class State:
    def __init__(self, backup: Any, *, kill: bool = False) -> None:
        self.backup = backup
        self.kill = kill

    async def get(self, key: str) -> Any:
        return self.backup if key == "last_backup_at" else None

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


def context(dry_run: bool = True) -> tuple[WriteContext, Audit]:
    audit = Audit()
    return (
        WriteContext(
            dry_run=dry_run,
            state=State(None),  # type: ignore[arg-type]
            audit=audit,
            per_run_budgets={("betterstack", "heartbeat"): 10},
            per_day_budgets={("betterstack", "heartbeat"): 400},
        ),
        audit,
    )


def health_context(
    http: ControlledClient,
    writes: WriteContext,
    *,
    backup: Any = None,
    disk: int = 20,
    aged: int = 0,
    errors: int = 0,
    kill: bool = False,
) -> HostHealthContext:
    backup = backup if backup is not None else {"at": (NOW - timedelta(hours=1)).isoformat()}
    return HostHealthContext(
        database=Database(aged, errors),  # type: ignore[arg-type]
        state=State(backup, kill=kill),  # type: ignore[arg-type]
        writes=writes,
        http=http,
        heartbeat_url=HttpUrl(URL),
        host_path=Path("synthetic"),
        clock=lambda: NOW,
        disk_usage=lambda _path: Usage(100, disk, 100 - disk),
    )


async def test_healthy_dry_run_skips_external_http() -> None:
    writes, audit = context()
    async with ControlledClient() as http:
        result = await run(health_context(http, writes))
    assert result.healthy and result.backup_age_hours == 1
    assert audit.rows == ["skipped"]


async def test_healthy_live_run_sends_heartbeat(respx_mock: object) -> None:
    writes, audit = context(dry_run=False)
    route = respx_mock.get(URL).mock(return_value=MockResponse(200))  # type: ignore[attr-defined]
    async with ControlledClient() as http:
        result = await run(health_context(http, writes))
    assert result.healthy and route.called
    assert audit.rows == ["ok"]


async def test_each_unhealthy_aggregate_suppresses_heartbeat() -> None:
    cases = [
        {"disk": 85},
        {"backup": {"at": (NOW - timedelta(hours=26)).isoformat()}},
        {"backup": {"at": "invalid"}},
        {"aged": 1},
        {"errors": 1},
        {"kill": True},
    ]
    for values in cases:
        writes, audit = context(dry_run=False)
        async with ControlledClient() as http:
            result = await run(health_context(http, writes, **values))
        assert not result.healthy
        assert audit.rows == []
