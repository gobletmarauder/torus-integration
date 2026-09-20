"""Bounded, idempotent Supabase-to-Zoho lead synchronization job."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import TypeAdapter

from tis.db import Database
from tis.errors import BudgetExceeded, DuplicateWrite, KillSwitchOn
from tis.guards import WriteContext
from tis.http import ControlledClient
from tis.integrations.zoho import ZohoAuth, upsert_lead
from tis.log import get_logger
from tis.mapping.lead_to_zoho import LeadRow, ZohoFieldMap, map_lead

MAX_BATCH_SIZE = 25
_LOG = get_logger("jobs.lead_sync")
_LEAD_ROWS = TypeAdapter(list[LeadRow])
_SELECT_PENDING = """
SELECT id, created_at, name, email, company, headcount_band, systems_named,
       calculator_annual_estimate, utm_source, utm_medium, utm_campaign,
       utm_content, utm_term, referrer, page_path, crm_synced,
       crm_sync_attempts, crm_last_error, COALESCE(is_test, false) AS is_test
FROM leads
WHERE crm_synced = false
  AND crm_sync_attempts < 10
  AND COALESCE(is_test, false) = false
ORDER BY created_at ASC, id ASC
LIMIT %s
FOR UPDATE SKIP LOCKED
"""
_MARK_SUCCESS = """
UPDATE leads
SET crm_synced = true, crm_synced_at = now(), zoho_lead_id = %s,
    crm_last_error = NULL
WHERE id = %s AND crm_synced = false
"""
_MARK_FAILURE = """
UPDATE leads
SET crm_sync_attempts = crm_sync_attempts + 1, crm_last_error = %s
WHERE id = %s AND crm_synced = false
"""


class LeadStore(Protocol):
    """Persistence contract for bounded lead work and write-back."""

    async def pending(self, *, batch_size: int) -> list[LeadRow]:
        """Return one locked, ordered work page."""

    async def mark_success(self, lead_id: UUID, zoho_id: str) -> None:
        """Mark one lead synchronized."""

    async def mark_failure(self, lead_id: UUID, error: str) -> None:
        """Increment one lead's bounded retry state."""


class PostgresLeadStore:
    """Read and update the authoritative public.leads table."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def pending(self, *, batch_size: int) -> list[LeadRow]:
        """Select at most 25 eligible rows with skip-locked ordering."""
        limit = min(max(batch_size, 1), MAX_BATCH_SIZE)
        rows = await self._database.fetch_all(_SELECT_PENDING, (limit,))
        return _LEAD_ROWS.validate_python(rows)

    async def mark_success(self, lead_id: UUID, zoho_id: str) -> None:
        """Persist the Zoho id and successful completion timestamp."""
        await self._database.execute(_MARK_SUCCESS, (zoho_id, lead_id))

    async def mark_failure(self, lead_id: UUID, error: str) -> None:
        """Increment attempts and persist a bounded error class only."""
        await self._database.execute(_MARK_FAILURE, (error[:120], lead_id))


@dataclass(frozen=True)
class JobResult:
    """Non-personal counters returned by a lead sync run."""

    selected: int
    succeeded: int
    skipped: int
    failed: int


@dataclass
class LeadSyncContext:
    """Dependencies and safe settings for one lead sync run."""

    writes: WriteContext
    store: LeadStore
    http: ControlledClient
    auth: ZohoAuth
    field_map: ZohoFieldMap
    api_url: str
    api_version: str = "v8"
    batch_size: int = MAX_BATCH_SIZE


async def run(ctx: LeadSyncContext) -> JobResult:
    """Process one bounded page; this may write to Zoho and lead status columns."""
    leads = await ctx.store.pending(batch_size=ctx.batch_size)
    succeeded = skipped = failed = 0
    for lead in leads:
        try:
            zoho_id = await upsert_lead(
                ctx.writes,
                map_lead(lead, ctx.field_map),
                ctx.http,
                ctx.auth,
                api_url=ctx.api_url,
                api_version=ctx.api_version,
            )
            if ctx.writes.dry_run:
                skipped += 1
                continue
            await ctx.store.mark_success(lead.id, zoho_id)
            succeeded += 1
        except KillSwitchOn:
            skipped += 1
        except DuplicateWrite as error:
            await ctx.store.mark_failure(lead.id, type(error).__name__)
            failed += 1
        except Exception as error:
            if not isinstance(error, BudgetExceeded):
                await ctx.store.mark_failure(lead.id, type(error).__name__)
            failed += 1
            _LOG.error(
                "lead_sync_item_failed",
                extra={"fields": {"error": type(error).__name__}},
            )
    return JobResult(len(leads), succeeded, skipped, failed)
