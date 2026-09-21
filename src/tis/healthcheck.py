"""Minimal container health probes for process, API, and scheduler roles."""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path
from typing import Literal

from tis.config import Settings, get_settings
from tis.db import PsycopgDatabase

Role = Literal["process", "api", "scheduler"]


async def check(role: Role, settings: Settings) -> bool:
    """Check one role; API mode briefly opens the configured database pool."""
    if role == "process":
        return True
    if role == "scheduler":
        return _watchdog_fresh(
            settings.scheduler_watchdog_path,
            settings.scheduler_watchdog_max_age_seconds,
        )
    if not settings.database_dsn:
        return False
    database = PsycopgDatabase(settings.database_dsn, min_size=1, max_size=1)
    try:
        await database.open()
        return int(await database.fetch_value("SELECT 1", ()) or 0) == 1
    except Exception:
        return False
    finally:
        await database.close()


def _watchdog_fresh(path: Path, max_age_seconds: int, *, now: float | None = None) -> bool:
    try:
        modified = path.stat().st_mtime
    except OSError:
        return False
    return 0 <= (now if now is not None else time.time()) - modified <= max_age_seconds


def main() -> None:
    """Run a bounded health probe and exit zero only on success."""
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("process", "api", "scheduler"))
    args = parser.parse_args()
    healthy = asyncio.run(check(args.role, get_settings()))
    raise SystemExit(0 if healthy else 1)


if __name__ == "__main__":
    main()
