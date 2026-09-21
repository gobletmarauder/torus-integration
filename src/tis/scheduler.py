"""Async scheduler process for all enabled integration jobs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

from tis.config import Settings
from tis.jobs import booking_sync, host_health, keepalive, lead_sync
from tis.log import configure_logging, get_logger, reset_correlation_id, set_correlation_id
from tis.runtime import Runtime, build_runtime

_LOG = get_logger("scheduler")
Runner = Callable[[], Awaitable[object]]


@dataclass(frozen=True)
class JobSpec:
    """One configured scheduled job and its exact interval."""

    name: str
    interval_seconds: int
    runner: Runner


def job_specs(runtime: Runtime) -> list[JobSpec]:
    """Build enabled job runners without starting the scheduler."""
    settings = runtime.settings
    specs: list[JobSpec] = []
    if runtime.lead is not None:
        lead_context = runtime.lead

        async def run_lead() -> object:
            return await lead_sync.run(replace(lead_context, writes=runtime.new_writes()))

        specs.append(JobSpec("lead_sync", settings.lead_sync_interval_seconds, run_lead))
    if runtime.booking is not None:
        booking_context = runtime.booking

        async def run_booking() -> object:
            return await booking_sync.run(replace(booking_context, writes=runtime.new_writes()))

        specs.append(JobSpec("booking_sync", settings.booking_sync_interval_seconds, run_booking))
    if settings.keepalive_enabled:
        keepalive_url = settings.betterstack_keepalive_url
        if keepalive_url is None:
            raise RuntimeError("keepalive heartbeat URL is missing")

        async def run_keepalive() -> object:
            context = keepalive.KeepaliveContext(
                database=runtime.database,
                writes=runtime.new_writes(),
                http=runtime.http,
                heartbeat_url=keepalive_url,
            )
            return await keepalive.run(context)

        specs.append(JobSpec("keepalive", settings.keepalive_interval_seconds, run_keepalive))
    if settings.host_health_enabled:
        host_health_url = settings.betterstack_host_health_url
        if host_health_url is None:
            raise RuntimeError("host-health heartbeat URL is missing")

        async def run_host_health() -> object:
            context = host_health.HostHealthContext(
                database=runtime.database,
                state=runtime.state,
                writes=runtime.new_writes(),
                http=runtime.http,
                heartbeat_url=host_health_url,
            )
            return await host_health.run(context)

        specs.append(JobSpec("host_health", settings.host_health_interval_seconds, run_host_health))
    return specs


def create_scheduler(runtime: Runtime) -> AsyncIOScheduler:
    """Configure enabled UTC interval jobs without starting execution."""
    scheduler = AsyncIOScheduler(timezone=UTC)
    scheduler.add_job(
        _touch_watchdog,
        "interval",
        args=(runtime.settings,),
        id="watchdog",
        seconds=30,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
    for spec in job_specs(runtime):
        scheduler.add_job(
            execute_job,
            "interval",
            args=(runtime, spec),
            id=spec.name,
            seconds=spec.interval_seconds,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )
    return scheduler


async def execute_job(runtime: Runtime, spec: JobSpec) -> None:
    """Run one job in isolation and persist only non-personal outcome state."""
    token = set_correlation_id()
    try:
        result = await spec.runner()
        if not _successful(result):
            raise RuntimeError("job reported an unhealthy or failed result")
        await runtime.state.mark_last_run(spec.name)
        _LOG.info("job_completed", extra={"fields": {"job": spec.name}})
    except Exception as error:
        await runtime.state.set(
            f"last_error:{spec.name}",
            {"at": datetime.now(UTC).isoformat(), "error": type(error).__name__},
        )
        _LOG.error(
            "job_failed",
            extra={"fields": {"job": spec.name, "error": type(error).__name__}},
        )
    finally:
        _touch_watchdog(runtime.settings)
        reset_correlation_id(token)


def _successful(result: object) -> bool:
    failed = getattr(result, "failed", 0)
    healthy = getattr(result, "healthy", True)
    return isinstance(failed, int) and failed == 0 and healthy is not False


def _touch_watchdog(settings: Settings) -> None:
    settings.scheduler_watchdog_path.parent.mkdir(parents=True, exist_ok=True)
    settings.scheduler_watchdog_path.touch()


async def serve(runtime: Runtime | None = None) -> None:
    """Open runtime resources and serve scheduled jobs until cancellation."""
    owned = runtime or build_runtime()
    await owned.open()
    scheduler = create_scheduler(owned)
    _touch_watchdog(owned.settings)
    scheduler.start()
    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown(wait=False)
        await owned.close()


def main() -> None:
    """Run the scheduler process; this opens configured DB/HTTP resources."""
    configure_logging()
    asyncio.run(serve())


if __name__ == "__main__":
    main()
