"""Scheduler configuration and isolation tests."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tis.config import Settings
from tis.scheduler import JobSpec, create_scheduler, execute_job, job_specs


class State:
    def __init__(self) -> None:
        self.runs: list[str] = []
        self.values: list[tuple[str, Any]] = []

    async def mark_last_run(self, job: str) -> None:
        self.runs.append(job)

    async def set(self, key: str, value: Any) -> None:
        self.values.append((key, value))


def runtime(tmp_path: Path, **settings: Any) -> SimpleNamespace:
    configured = Settings(
        database_dsn="postgresql://synthetic.invalid/db",
        scheduler_watchdog_path=tmp_path / "watchdog",
        **settings,
        _env_file=None,
    )
    return SimpleNamespace(
        settings=configured,
        lead=None,
        booking=None,
        database=SimpleNamespace(),
        state=State(),
        http=SimpleNamespace(),
        new_writes=lambda: SimpleNamespace(),
    )


def test_scheduler_registers_health_jobs_with_safety_options(tmp_path: Path) -> None:
    value = runtime(
        tmp_path,
        keepalive_enabled=True,
        host_health_enabled=True,
        betterstack_keepalive_url="https" + "://uptime.betterstack.com/synthetic-a",
        betterstack_host_health_url="https" + "://uptime.betterstack.com/synthetic-b",
    )
    value.lead = SimpleNamespace()
    value.booking = SimpleNamespace()
    specs = job_specs(value)  # type: ignore[arg-type]
    assert [(spec.name, spec.interval_seconds) for spec in specs] == [
        ("lead_sync", 30),
        ("booking_sync", 120),
        ("keepalive", 86_400),
        ("host_health", 300),
    ]
    scheduler = create_scheduler(value)  # type: ignore[arg-type]
    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {"watchdog", "lead_sync", "booking_sync", "keepalive", "host_health"}
    assert all(job.max_instances == 1 for job in jobs.values())
    assert all(job.coalesce is True and job.misfire_grace_time == 60 for job in jobs.values())


async def test_execute_job_records_success_and_touches_watchdog(tmp_path: Path) -> None:
    value = runtime(tmp_path)

    async def runner() -> object:
        return SimpleNamespace(failed=0)

    await execute_job(value, JobSpec("synthetic", 30, runner))  # type: ignore[arg-type]
    assert value.state.runs == ["synthetic"]
    assert value.state.values == []
    assert value.settings.scheduler_watchdog_path.exists()


async def test_execute_job_isolates_error_and_records_class_only(tmp_path: Path) -> None:
    value = runtime(tmp_path)

    async def runner() -> object:
        raise ValueError("sensitive synthetic detail")

    await execute_job(value, JobSpec("synthetic", 30, runner))  # type: ignore[arg-type]
    assert value.state.runs == []
    key, stored = value.state.values[0]
    assert key == "last_error:synthetic" and stored["error"] == "ValueError"
    assert "sensitive" not in str(stored)


async def test_unhealthy_result_is_not_recorded_as_success(tmp_path: Path) -> None:
    value = runtime(tmp_path)

    async def runner() -> object:
        return SimpleNamespace(healthy=False)

    await execute_job(value, JobSpec("host_health", 300, runner))  # type: ignore[arg-type]
    assert value.state.runs == []
    assert value.state.values[0][0] == "last_error:host_health"
