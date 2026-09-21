"""Fail-closed aggregate host and synchronization health check."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import HttpUrl

from tis.db import Database
from tis.guards import WriteContext
from tis.http import ControlledClient
from tis.integrations.betterstack import Heartbeat, send_heartbeat
from tis.state import StateStore

_AGED_LEADS = """
SELECT count(*) FROM leads
WHERE crm_synced = false AND created_at < now() - interval '30 minutes'
"""
_BOOKING_ERRORS = """
SELECT count(*) FROM integration_log
WHERE source = 'google_calendar' AND action = 'sync_booking'
  AND status = 'error' AND updated_at >= now() - interval '1 hour'
"""


@dataclass(frozen=True)
class JobResult:
    """Non-personal health result and bounded aggregate counters."""

    healthy: bool
    disk_percent: float
    backup_age_hours: float | None
    aged_leads: int
    booking_errors: int
    kill_switch: bool


class DiskUsage(Protocol):
    """Structural subset returned by shutil.disk_usage."""

    @property
    def total(self) -> int: ...

    @property
    def used(self) -> int: ...

    @property
    def free(self) -> int: ...


def _disk_usage(path: Path) -> DiskUsage:
    return shutil.disk_usage(path)


@dataclass
class HostHealthContext:
    """Dependencies for aggregate host health and conditional heartbeat."""

    database: Database
    state: StateStore
    writes: WriteContext
    http: ControlledClient
    heartbeat_url: HttpUrl
    host_path: Path = Path("/host-state")
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    disk_usage: Callable[[Path], DiskUsage] = _disk_usage


async def run(ctx: HostHealthContext) -> JobResult:
    """Evaluate all health conditions and heartbeat only when every one passes."""
    usage = ctx.disk_usage(ctx.host_path)
    disk_percent = (usage.used / usage.total * 100.0) if usage.total else 100.0
    backup = _state_timestamp(await ctx.state.get("last_backup_at"))
    now = ctx.clock().astimezone(UTC)
    backup_age = (now - backup).total_seconds() / 3600 if backup else None
    aged_leads = int(await ctx.database.fetch_value(_AGED_LEADS, ()) or 0)
    booking_errors = int(await ctx.database.fetch_value(_BOOKING_ERRORS, ()) or 0)
    kill_switch = await ctx.state.kill_switch_on()
    healthy = (
        disk_percent < 85
        and backup_age is not None
        and 0 <= backup_age < 26
        and aged_leads == 0
        and booking_errors == 0
        and not kill_switch
    )
    if healthy:
        run_id = now.strftime("%Y-%m-%dT%H:%M")
        await send_heartbeat(
            ctx.writes,
            Heartbeat(monitor="tis-health", run_id=run_id, url=ctx.heartbeat_url),
            ctx.http,
        )
    return JobResult(healthy, disk_percent, backup_age, aged_leads, booking_errors, kill_switch)


def _state_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, Mapping) or not isinstance(value.get("at"), str):
        return None
    try:
        parsed = datetime.fromisoformat(str(value["at"]).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)
