"""Central guard for idempotent, budgeted, kill-switch-aware external writes."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import wraps
from typing import Any, ParamSpec, Protocol, TypeVar, cast

from tis.db import Database
from tis.errors import BudgetExceeded, DuplicateWrite, KillSwitchOn
from tis.log import correlation_id, get_logger
from tis.state import StateStore

P = ParamSpec("P")
R = TypeVar("R")
_LOG = get_logger("guards")
_STATUS = """
SELECT status FROM integration_log
WHERE source = %s AND external_id = %s AND action = %s
"""
_COUNT_DAY = """
SELECT count(*) AS count FROM integration_log
WHERE source = %s AND action = %s AND status = 'ok' AND updated_at >= %s
"""
_CLAIM = """
INSERT INTO integration_log
    (source, external_id, action, status, attempts, error, payload, updated_at)
VALUES (%s, %s, %s, 'skipped', 0, NULL, jsonb_build_object('guard_status', 'pending'), now())
ON CONFLICT (source, external_id, action) DO UPDATE SET
    status = 'skipped',
    error = NULL,
    payload = EXCLUDED.payload,
    updated_at = now()
WHERE integration_log.status IN ('error', 'skipped')
  AND COALESCE(integration_log.payload->>'guard_status', '') <> 'pending'
RETURNING id
"""
_UPSERT = """
INSERT INTO integration_log
    (source, external_id, action, status, attempts, error, payload, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, now())
ON CONFLICT (source, external_id, action) DO UPDATE SET
    status = EXCLUDED.status,
    attempts = integration_log.attempts +
        CASE WHEN EXCLUDED.status IN ('ok', 'error') THEN 1 ELSE 0 END,
    error = EXCLUDED.error,
    payload = EXCLUDED.payload,
    updated_at = now()
"""


class AuditStore(Protocol):
    """Persistence contract used by the external-write guard."""

    async def status(self, source: str, external_id: str, action: str) -> str | None:
        """Return the prior terminal status, if any."""

    async def successful_today(self, source: str, action: str, since: datetime) -> int:
        """Count successful writes since the supplied UTC boundary."""

    async def claim(self, source: str, external_id: str, action: str) -> bool:
        """Atomically claim an idempotency key for one live write."""

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
        """Upsert a redacted audit result."""


class PostgresAuditStore:
    """Persist idempotency and audit rows in public.integration_log."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def status(self, source: str, external_id: str, action: str) -> str | None:
        """Read one idempotency status from integration_log."""
        row = await self._database.fetch_one(_STATUS, (source, external_id, action))
        return str(row["status"]) if row else None

    async def successful_today(self, source: str, action: str, since: datetime) -> int:
        """Count successful writes since the UTC day boundary."""
        value = await self._database.fetch_value(_COUNT_DAY, (source, action, since))
        return int(value or 0)

    async def claim(self, source: str, external_id: str, action: str) -> bool:
        """Atomically reserve one idempotency key across concurrent job runs."""
        row = await self._database.fetch_one(_CLAIM, (source, external_id, action))
        return row is not None

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
        """Upsert a redacted audit result using the authoritative conflict key."""
        if status not in {"ok", "error", "skipped"}:
            raise ValueError("invalid integration_log status")
        await self._database.execute(
            _UPSERT,
            (source, external_id, action, status, 1, error, dict(payload or {})),
        )


@dataclass
class WriteContext:
    """Dependencies and counters shared by guarded writes in one job run."""

    dry_run: bool
    state: StateStore
    audit: AuditStore
    per_run_budgets: Mapping[tuple[str, str], int]
    per_day_budgets: Mapping[tuple[str, str], int]
    run_counts: defaultdict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))


KeyFunction = Callable[..., str]


def external_write(
    *, source: str, action: str, key: KeyFunction
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Guard an external write; the wrapped call may perform remote side effects."""

    def decorate(function: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(function)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            if not args or not isinstance(args[0], WriteContext):
                raise TypeError("guarded writes require WriteContext as the first argument")
            context = args[0]
            external_id = key(*args[1:], **kwargs)
            budget_key = (source, action)
            if await context.state.kill_switch_on():
                await context.audit.record(source, external_id, action, "skipped")
                raise KillSwitchOn("external writes are disabled")
            if context.dry_run:
                await context.audit.record(source, external_id, action, "skipped")
                _LOG.info(
                    "external_write_skipped", extra={"fields": {"source": source, "action": action}}
                )
                return cast(R, None)
            try:
                await _enforce_budget(context, budget_key)
            except BudgetExceeded as error:
                await context.audit.record(
                    source,
                    external_id,
                    action,
                    "error",
                    error=type(error).__name__,
                )
                raise
            if not await context.audit.claim(source, external_id, action):
                raise DuplicateWrite("external write is complete or already in progress")
            try:
                result = await function(*args, **kwargs)
            except Exception as error:
                await context.audit.record(
                    source,
                    external_id,
                    action,
                    "error",
                    error=type(error).__name__,
                )
                raise
            await context.audit.record(source, external_id, action, "ok")
            context.run_counts[budget_key] += 1
            return result

        return wrapped

    return decorate


async def _enforce_budget(context: WriteContext, budget_key: tuple[str, str]) -> None:
    source, action = budget_key
    per_run = context.per_run_budgets[budget_key]
    per_day = context.per_day_budgets[budget_key]
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    if context.run_counts[budget_key] >= per_run:
        raise BudgetExceeded("per-run external-write budget exhausted")
    if await context.audit.successful_today(source, action, day_start) >= per_day:
        raise BudgetExceeded("daily external-write budget exhausted")
    _LOG.debug(
        "external_write_allowed",
        extra={"fields": {"source": source, "action": action, "correlation_id": correlation_id()}},
    )
