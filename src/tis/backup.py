"""Guarded R2 backup operations and the backup-container command line."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from tis.config import Settings, get_settings
from tis.db import PsycopgDatabase
from tis.guards import PostgresAuditStore, WriteContext, external_write
from tis.http import client
from tis.integrations.betterstack import Heartbeat, send_heartbeat
from tis.state import StateStore

BACKUP_OBJECT = re.compile(r"^torus-backup-(\d{4}-\d{2}-\d{2})\.dump\.gz\.age$")
MAX_RETENTION_DELETES = 10


class BackupRequest(BaseModel):
    """Validated local-to-R2 upload description with no credential fields."""

    model_config = ConfigDict(extra="forbid")

    local_path: Path
    object_name: str
    backup_date: date


class RetentionRequest(BaseModel):
    """One bounded retention pass identified by UTC date."""

    model_config = ConfigDict(extra="forbid")

    run_date: date


class Runner(Protocol):
    """Execute a fixed argv without a shell."""

    async def run(self, argv: Sequence[str], env: Mapping[str, str]) -> str:
        """Run one command and return bounded stdout or raise on failure."""


class SubprocessRunner:
    """Run trusted backup binaries without exposing their environment."""

    async def run(self, argv: Sequence[str], env: Mapping[str, str]) -> str:
        """Execute argv directly; this may perform R2 network I/O."""
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=dict(env),
        )
        stdout, _stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError("backup transport command failed")
        if len(stdout) > 1_000_000:
            raise RuntimeError("backup transport output exceeded limit")
        return stdout.decode("utf-8", errors="strict")


@dataclass(frozen=True)
class RcloneTransport:
    """R2-only rclone transport whose methods may perform remote reads or writes."""

    runner: Runner
    environment: Mapping[str, str] = field(repr=False)
    bucket: str

    def remote(self, object_name: str = "") -> str:
        """Return a validated remote path without issuing I/O."""
        if self.bucket != "torus-backups":
            raise ValueError("unexpected backup bucket")
        if object_name and BACKUP_OBJECT.fullmatch(object_name) is None:
            raise ValueError("unexpected backup object name")
        suffix = f"/{object_name}" if object_name else ""
        return f"torus:{self.bucket}{suffix}"

    async def exists(self, object_name: str) -> bool:
        """Return whether the exact encrypted object already exists."""
        output = await self.runner.run(
            ["rclone", "lsf", "--files-only", "--include", object_name, self.remote()],
            self.environment,
        )
        return output.strip() == object_name

    async def upload(self, local_path: Path, object_name: str) -> None:
        """Upload one encrypted object and verify that it is visible remotely."""
        if not local_path.is_file() or local_path.suffix != ".age":
            raise ValueError("backup upload requires an encrypted file")
        if await self.exists(object_name):
            return
        await self.runner.run(
            ["rclone", "copyto", "--immutable", str(local_path), self.remote(object_name)],
            self.environment,
        )
        if not await self.exists(object_name):
            raise RuntimeError("uploaded backup could not be verified")

    async def list_objects(self) -> list[str]:
        """List only validated Torus backup object names."""
        output = await self.runner.run(
            ["rclone", "lsf", "--files-only", self.remote()], self.environment
        )
        names = [line.strip() for line in output.splitlines() if line.strip()]
        if any(BACKUP_OBJECT.fullmatch(name) is None for name in names):
            raise RuntimeError("R2 listing contained an out-of-prefix object")
        return names

    async def delete(self, object_name: str) -> None:
        """Remove exactly one validated surplus Torus backup object."""
        await self.runner.run(["rclone", "deletefile", self.remote(object_name)], self.environment)

    async def download_latest(self, target: Path) -> str:
        """Download the newest validated encrypted backup to a tmpfs target."""
        objects = self._dated(await self.list_objects())
        if not objects:
            raise RuntimeError("no backup object is available")
        newest = objects[-1][1]
        await self.runner.run(
            ["rclone", "copyto", self.remote(newest), str(target)], self.environment
        )
        return newest

    @staticmethod
    def _dated(objects: Sequence[str]) -> list[tuple[date, str]]:
        dated: list[tuple[date, str]] = []
        for name in objects:
            match = BACKUP_OBJECT.fullmatch(name)
            if match is None:
                raise RuntimeError("invalid backup object")
            dated.append((date.fromisoformat(match.group(1)), name))
        return sorted(dated)


@external_write(
    source="r2",
    action="upload_backup",
    key=lambda request, *_args, **_kwargs: f"backup:{request.backup_date.isoformat()}",
)
async def upload_backup(
    context: WriteContext,
    request: BackupRequest,
    transport: RcloneTransport,
    state: StateStore,
) -> None:
    """Upload one encrypted daily backup and record aggregate success state."""
    expected = f"torus-backup-{request.backup_date.isoformat()}.dump.gz.age"
    if request.object_name != expected:
        raise ValueError("backup object date does not match")
    await transport.upload(request.local_path, request.object_name)
    await state.set("last_backup_at", {"at": datetime.now(UTC).isoformat()})


@external_write(
    source="r2",
    action="prune_backups",
    key=lambda request, *_args, **_kwargs: f"retention:{request.run_date.isoformat()}",
)
async def prune_backups(
    context: WriteContext, request: RetentionRequest, transport: RcloneTransport
) -> None:
    """Remove bounded surplus Torus backups according to 7-daily/4-weekly retention."""
    objects = await transport.list_objects()
    for object_name in retention_deletions(objects)[:MAX_RETENTION_DELETES]:
        await transport.delete(object_name)


def retention_deletions(objects: Sequence[str]) -> list[str]:
    """Return oldest objects not selected for seven daily and four prior weekly slots."""
    dated = RcloneTransport._dated(objects)
    newest_daily = {name for _, name in dated[-7:]}
    weekly: dict[tuple[int, int], str] = {}
    for backup_date, name in reversed(dated[:-7]):
        iso = backup_date.isocalendar()
        weekly.setdefault((iso.year, iso.week), name)
        if len(weekly) == 4:
            break
    keep = newest_daily | set(weekly.values())
    return [name for _, name in dated if name not in keep]


def _transport(settings: Settings, runner: Runner | None = None) -> RcloneTransport:
    access_key = settings.r2_access_key_id
    secret_key = settings.r2_secret_access_key
    endpoint = settings.r2_endpoint
    bucket = settings.r2_bucket
    if access_key is None or secret_key is None or endpoint is None or bucket is None:
        raise RuntimeError("backup R2 configuration is incomplete")
    environment = {
        **os.environ,
        "RCLONE_CONFIG_TORUS_TYPE": "s3",
        "RCLONE_CONFIG_TORUS_PROVIDER": "Cloudflare",
        "RCLONE_CONFIG_TORUS_ACCESS_KEY_ID": access_key.get_secret_value(),
        "RCLONE_CONFIG_TORUS_SECRET_ACCESS_KEY": secret_key.get_secret_value(),
        "RCLONE_CONFIG_TORUS_ENDPOINT": str(endpoint).rstrip("/"),
        "RCLONE_CONFIG_TORUS_NO_CHECK_BUCKET": "true",
    }
    return RcloneTransport(runner or SubprocessRunner(), environment, bucket)


def _write_context(
    settings: Settings, state: StateStore, audit: PostgresAuditStore
) -> WriteContext:
    return WriteContext(
        dry_run=settings.dry_run,
        state=state,
        audit=audit,
        per_run_budgets={
            ("r2", "upload_backup"): settings.r2_upload_budget_per_run,
            ("r2", "prune_backups"): settings.r2_retention_budget_per_run,
            ("betterstack", "heartbeat"): settings.betterstack_budget_per_run,
        },
        per_day_budgets={
            ("r2", "upload_backup"): settings.r2_upload_budget_per_day,
            ("r2", "prune_backups"): settings.r2_retention_budget_per_day,
            ("betterstack", "heartbeat"): settings.betterstack_budget_per_day,
        },
    )


async def _run_command(args: argparse.Namespace, settings: Settings) -> None:
    if settings.backup_database_dsn is None:
        raise RuntimeError("BACKUP_DATABASE_DSN is required")
    database = PsycopgDatabase(settings.backup_database_dsn.get_secret_value())
    state = StateStore(database)
    audit = PostgresAuditStore(database)
    writes = _write_context(settings, state, audit)
    transport = _transport(settings)
    await database.open()
    try:
        if args.command == "upload":
            backup_date = date.fromisoformat(args.date)
            await upload_backup(
                writes,
                BackupRequest(
                    local_path=Path(args.path),
                    object_name=args.object,
                    backup_date=backup_date,
                ),
                transport,
                state,
            )
        elif args.command == "prune":
            await prune_backups(
                writes, RetentionRequest(run_date=date.fromisoformat(args.date)), transport
            )
        elif args.command == "download":
            if settings.dry_run:
                return
            await transport.download_latest(Path(args.path))
        elif args.command == "heartbeat":
            url = (
                settings.betterstack_backup_url
                if args.monitor == "tis-backup"
                else settings.betterstack_restore_test_url
            )
            if url is None:
                raise RuntimeError("backup heartbeat URL is missing")
            async with client() as http:
                await send_heartbeat(
                    writes,
                    Heartbeat(monitor=args.monitor, run_id=args.run_id, url=url),
                    http,
                )
    finally:
        await database.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    upload = subparsers.add_parser("upload")
    upload.add_argument("--path", required=True)
    upload.add_argument("--object", required=True)
    upload.add_argument("--date", required=True)
    prune = subparsers.add_parser("prune")
    prune.add_argument("--date", required=True)
    download = subparsers.add_parser("download")
    download.add_argument("--path", required=True)
    heartbeat = subparsers.add_parser("heartbeat")
    heartbeat.add_argument("--monitor", choices=("tis-backup", "tis-restore-test"), required=True)
    heartbeat.add_argument("--run-id", required=True)
    return parser


def main() -> int:
    """Run one backup-container operation; this may access DB, R2, or Better Stack."""
    asyncio.run(_run_command(_parser().parse_args(), get_settings()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
