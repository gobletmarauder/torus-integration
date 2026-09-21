"""Guarded backup transport and retention tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from tis.backup import (
    BackupRequest,
    RcloneTransport,
    RetentionRequest,
    _transport,
    prune_backups,
    retention_deletions,
    upload_backup,
)
from tis.config import Settings
from tis.errors import KillSwitchOn
from tis.guards import WriteContext


class FakeState:
    def __init__(self, killed: bool = False) -> None:
        self.killed = killed
        self.values: dict[str, Mapping[str, Any]] = {}

    async def kill_switch_on(self) -> bool:
        return self.killed

    async def set(self, key: str, value: Mapping[str, Any]) -> None:
        self.values[key] = value


class FakeAudit:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

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
        self.rows.append((source, external_id, action, status))


class FakeRunner:
    def __init__(self, listing: Sequence[str] = ()) -> None:
        self.listing = list(listing)
        self.calls: list[list[str]] = []
        self.uploaded = False

    async def run(self, argv: Sequence[str], env: Mapping[str, str]) -> str:
        self.calls.append(list(argv))
        assert "synthetic-secret" not in " ".join(argv)
        if argv[1] == "lsf" and "--include" in argv:
            return argv[argv.index("--include") + 1] if self.uploaded else ""
        if argv[1] == "copyto":
            self.uploaded = True
            return ""
        if argv[1] == "lsf":
            return "\n".join(self.listing)
        return ""


def context(*, dry_run: bool = False, killed: bool = False) -> tuple[WriteContext, FakeAudit]:
    audit = FakeAudit()
    writes = WriteContext(
        dry_run=dry_run,
        state=FakeState(killed),  # type: ignore[arg-type]
        audit=audit,
        per_run_budgets={("r2", "upload_backup"): 1, ("r2", "prune_backups"): 1},
        per_day_budgets={("r2", "upload_backup"): 1, ("r2", "prune_backups"): 1},
    )
    return writes, audit


def transport(runner: FakeRunner) -> RcloneTransport:
    return RcloneTransport(
        runner, {"RCLONE_CONFIG_TORUS_SECRET_ACCESS_KEY": "synthetic-secret"}, "torus-backups"
    )


async def test_upload_is_guarded_and_idempotent_by_utc_date(tmp_path: Path) -> None:
    encrypted = tmp_path / "backup.age"
    encrypted.write_text("synthetic ciphertext", encoding="utf-8")
    runner = FakeRunner()
    writes, audit = context()
    request = BackupRequest(
        local_path=encrypted,
        object_name="torus-backup-2026-09-20.dump.gz.age",
        backup_date=date(2026, 9, 20),
    )

    await upload_backup(writes, request, transport(runner), writes.state)

    assert any(call[1] == "copyto" for call in runner.calls)
    assert audit.rows[-1] == ("r2", "backup:2026-09-20", "upload_backup", "ok")
    assert "last_backup_at" in writes.state.values  # type: ignore[attr-defined]


async def test_dry_run_and_kill_switch_make_zero_r2_calls(tmp_path: Path) -> None:
    encrypted = tmp_path / "backup.age"
    encrypted.write_text("synthetic ciphertext", encoding="utf-8")
    request = BackupRequest(
        local_path=encrypted,
        object_name="torus-backup-2026-09-20.dump.gz.age",
        backup_date=date(2026, 9, 20),
    )
    for dry_run, killed in ((True, False), (False, True)):
        runner = FakeRunner()
        writes, audit = context(dry_run=dry_run, killed=killed)
        if killed:
            with pytest.raises(KillSwitchOn):
                await upload_backup(writes, request, transport(runner), writes.state)
        else:
            await upload_backup(writes, request, transport(runner), writes.state)
        assert runner.calls == []
        assert audit.rows[-1][-1] == "skipped"
        assert writes.state.values == {}  # type: ignore[attr-defined]


def test_retention_keeps_seven_daily_and_four_older_weeks() -> None:
    objects = [f"torus-backup-2026-08-{day:02d}.dump.gz.age" for day in range(1, 32)]
    deleted = retention_deletions(objects)
    kept = set(objects) - set(deleted)

    assert set(objects[-7:]).issubset(kept)
    assert len(kept) == 11


async def test_prune_is_bounded_and_rejects_out_of_prefix_listing() -> None:
    valid = [f"torus-backup-2026-08-{day:02d}.dump.gz.age" for day in range(1, 32)]
    runner = FakeRunner(valid)
    writes, _audit = context()
    await prune_backups(writes, RetentionRequest(run_date=date(2026, 9, 20)), transport(runner))
    deletes = [call for call in runner.calls if call[1] == "deletefile"]
    assert len(deletes) == 10
    assert all("torus-backup-" in call[-1] for call in deletes)

    bad_runner = FakeRunner(["unrelated-object.age"])
    bad_writes, _ = context()
    with pytest.raises(RuntimeError, match="out-of-prefix"):
        await prune_backups(
            bad_writes,
            RetentionRequest(run_date=date(2026, 9, 20)),
            transport(bad_runner),
        )


def test_transport_accepts_only_exact_bucket_and_account_scoped_endpoint() -> None:
    settings = Settings(
        r2_access_key_id="synthetic-access",
        r2_secret_access_key="synthetic-secret",  # noqa: S106
        r2_endpoint="https" + "://synthetic-account.r2.cloudflarestorage.com",
        r2_bucket="torus-backups",
        _env_file=None,
    )
    value = _transport(settings, FakeRunner())
    assert value.bucket == "torus-backups"
    assert "synthetic-secret" not in repr(value)

    with pytest.raises(ValueError):
        value.remote("outside-prefix.age")
