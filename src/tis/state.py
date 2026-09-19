"""Typed access to integration state, including a short-lived kill-switch cache."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from tis.db import Database

_GET_STATE = "SELECT value FROM integration_state WHERE key = %s"
_SET_STATE = """
INSERT INTO integration_state (key, value, updated_at)
VALUES (%s, %s, now())
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
"""
KILL_SWITCH_CACHE_SECONDS = 15.0


class StateStore:
    """Read and update service-only integration state in PostgreSQL."""

    def __init__(
        self,
        database: Database,
        *,
        clock: Callable[[], float] = time.monotonic,
        cache_seconds: float = KILL_SWITCH_CACHE_SECONDS,
    ) -> None:
        self._database = database
        self._clock = clock
        self._cache_seconds = cache_seconds
        self._kill_switch_cache: tuple[float, bool] | None = None

    async def get(self, key: str) -> Any:
        """Read a JSON value from integration_state."""
        row = await self._database.fetch_one(_GET_STATE, (key,))
        return row.get("value") if row else None

    async def set(self, key: str, value: Any) -> None:
        """Upsert a JSON value in integration_state."""
        await self._database.execute(_SET_STATE, (key, value))
        if key == "kill_switch":
            self._kill_switch_cache = None

    async def kill_switch_on(self) -> bool:
        """Read the kill switch at most once per fifteen-second cache window."""
        now = self._clock()
        if self._kill_switch_cache and now - self._kill_switch_cache[0] < self._cache_seconds:
            return self._kill_switch_cache[1]
        value = await self.get("kill_switch")
        enabled = isinstance(value, Mapping) and value.get("on") is True
        self._kill_switch_cache = (now, enabled)
        return enabled

    async def mark_last_run(self, job: str, occurred_at: datetime | None = None) -> None:
        """Store a UTC job completion timestamp in integration_state."""
        timestamp = (occurred_at or datetime.now(UTC)).astimezone(UTC)
        await self.set(f"last_run:{job}", {"at": timestamp.isoformat()})
