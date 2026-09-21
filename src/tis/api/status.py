"""Non-personal operational status aggregation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from tis import VERSION
from tis.config import Settings
from tis.db import Database
from tis.state import StateStore

_JOB_STATE = """
SELECT key, value FROM integration_state
WHERE key LIKE 'last_run:%' OR key LIKE 'last_error:%'
ORDER BY key
"""
_WRITE_COUNTS = """
SELECT source, action, status, count(*) AS count
FROM integration_log
WHERE updated_at >= %s
GROUP BY source, action, status
ORDER BY source, action, status
"""
_LEAD_COUNTS = """
SELECT count(*) FILTER (WHERE crm_synced = false) AS unsynced,
       count(*) FILTER (
           WHERE crm_synced = false AND created_at < now() - interval '30 minutes'
       ) AS aged
FROM leads
"""
_BOOKING_ERRORS = """
SELECT count(*) FROM integration_log
WHERE source = 'google_calendar' AND action = 'sync_booking'
  AND status = 'error' AND updated_at >= now() - interval '1 hour'
"""


class JobStatus(BaseModel):
    """Non-personal timestamps for one scheduled job."""

    name: str
    last_success: datetime | None = None
    last_error: datetime | None = None


class WriteCount(BaseModel):
    """Aggregate guarded-write count and configured daily ceiling."""

    source: str
    action: str
    status: str
    count: int
    daily_budget: int | None = None


class OpsStatus(BaseModel):
    """Closed status response that intentionally excludes record-level data."""

    model_config = ConfigDict(extra="forbid")

    version: str
    image_digest: str
    dry_run: bool
    kill_switch: bool
    jobs: list[JobStatus]
    writes_today: list[WriteCount]
    unsynced_leads: int
    aged_unsynced_leads: int
    booking_errors_last_hour: int
    last_backup_at: datetime | None
    last_restore_test_at: datetime | None


class StatusService:
    """Read fixed aggregate queries; calls affect only the configured database."""

    def __init__(self, database: Database, state: StateStore, settings: Settings) -> None:
        self._database = database
        self._state = state
        self._settings = settings

    async def snapshot(self) -> OpsStatus:
        """Return a non-personal point-in-time operational snapshot."""
        day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        job_rows = await self._database.fetch_all(_JOB_STATE, ())
        write_rows = await self._database.fetch_all(_WRITE_COUNTS, (day_start,))
        lead_row = await self._database.fetch_one(_LEAD_COUNTS, ()) or {}
        booking_errors = int(await self._database.fetch_value(_BOOKING_ERRORS, ()) or 0)
        return OpsStatus(
            version=VERSION,
            image_digest=self._settings.tis_digest,
            dry_run=self._settings.dry_run,
            kill_switch=await self._state.kill_switch_on(),
            jobs=_jobs(job_rows),
            writes_today=_writes(write_rows, self._settings),
            unsynced_leads=int(lead_row.get("unsynced") or 0),
            aged_unsynced_leads=int(lead_row.get("aged") or 0),
            booking_errors_last_hour=booking_errors,
            last_backup_at=_timestamp(await self._state.get("last_backup_at")),
            last_restore_test_at=_timestamp(await self._state.get("last_restore_test_at")),
        )


def _jobs(rows: list[Mapping[str, Any]]) -> list[JobStatus]:
    values: dict[str, JobStatus] = {}
    for row in rows:
        key = str(row.get("key", ""))
        prefix, separator, name = key.partition(":")
        if not separator or prefix not in {"last_run", "last_error"}:
            continue
        status = values.setdefault(name, JobStatus(name=name))
        timestamp = _timestamp(row.get("value"))
        if prefix == "last_run":
            status.last_success = timestamp
        else:
            status.last_error = timestamp
    return [values[name] for name in sorted(values)]


def _writes(rows: list[Mapping[str, Any]], settings: Settings) -> list[WriteCount]:
    budgets = {
        ("posthog", "capture"): settings.posthog_budget_per_day,
        ("betterstack", "heartbeat"): settings.betterstack_budget_per_day,
        ("zoho", "upsert_lead"): settings.zoho_create_budget_per_day,
        ("google_calendar", "sync_booking"): settings.zoho_booking_budget_per_day,
    }
    return [
        WriteCount(
            source=str(row["source"]),
            action=str(row["action"]),
            status=str(row["status"]),
            count=int(row["count"]),
            daily_budget=budgets.get((str(row["source"]), str(row["action"]))),
        )
        for row in rows
    ]


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, Mapping) or not isinstance(value.get("at"), str):
        return None
    try:
        parsed = datetime.fromisoformat(str(value["at"]).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None
