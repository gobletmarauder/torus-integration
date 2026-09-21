"""Container healthcheck tests."""

import os
from pathlib import Path

from tis.config import Settings
from tis.healthcheck import _watchdog_fresh, check


async def test_process_and_missing_database_modes() -> None:
    settings = Settings(_env_file=None)
    assert await check("process", settings)
    assert not await check("api", settings)


async def test_scheduler_watchdog_must_exist_and_be_recent(tmp_path: Path) -> None:
    path = tmp_path / "watchdog"
    settings = Settings(scheduler_watchdog_path=path, _env_file=None)
    assert not await check("scheduler", settings)
    path.touch()
    modified = path.stat().st_mtime
    assert _watchdog_fresh(path, 90, now=modified + 89)
    assert not _watchdog_fresh(path, 90, now=modified + 91)
    os.utime(path, (modified + 100, modified + 100))
    assert not _watchdog_fresh(path, 90, now=modified)
