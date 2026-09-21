"""Daily database keepalive followed by a guarded Better Stack heartbeat."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import HttpUrl

from tis.db import Database
from tis.guards import WriteContext
from tis.http import ControlledClient
from tis.integrations.betterstack import Heartbeat, send_heartbeat

_SELECT_ONE = "SELECT 1"


@dataclass(frozen=True)
class JobResult:
    """Non-personal keepalive outcome."""

    selected: int
    succeeded: int
    skipped: int
    failed: int


@dataclass
class KeepaliveContext:
    """Dependencies for one read-only database keepalive run."""

    database: Database
    writes: WriteContext
    http: ControlledClient
    heartbeat_url: HttpUrl
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


async def run(ctx: KeepaliveContext) -> JobResult:
    """Round-trip PostgreSQL and then attempt one guarded external heartbeat."""
    await ctx.database.fetch_value(_SELECT_ONE, ())
    run_id = ctx.clock().astimezone(UTC).strftime("%Y-%m-%d")
    await send_heartbeat(
        ctx.writes,
        Heartbeat(monitor="tis-keepalive", run_id=run_id, url=ctx.heartbeat_url),
        ctx.http,
    )
    skipped = int(ctx.writes.dry_run)
    return JobResult(selected=1, succeeded=1 - skipped, skipped=skipped, failed=0)
