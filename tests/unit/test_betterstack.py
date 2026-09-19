"""Better Stack integration tests."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from respx import MockResponse

from tis.guards import WriteContext
from tis.http import EGRESS_ALLOWLIST, ControlledClient
from tis.integrations.betterstack import Heartbeat, send_heartbeat

BETTERSTACK_HOST = "uptime.betterstack.com"


class State:
    async def kill_switch_on(self) -> bool:
        return False


class Audit:
    def __init__(self) -> None:
        self.rows: list[str] = []

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
        self.rows.append(status)


def write_context(dry_run: bool = False) -> tuple[WriteContext, Audit]:
    audit = Audit()
    return (
        WriteContext(
            dry_run=dry_run,
            state=State(),  # type: ignore[arg-type]
            audit=audit,
            per_run_budgets={("betterstack", "heartbeat"): 10},
            per_day_budgets={("betterstack", "heartbeat"): 400},
        ),
        audit,
    )


async def test_heartbeat_uses_exact_host_and_idempotency_key(respx_mock: object) -> None:
    url = f"https://{BETTERSTACK_HOST}/heartbeat/synthetic"
    route = respx_mock.get(url).mock(  # type: ignore[attr-defined]
        return_value=MockResponse(200)
    )
    context, audit = write_context()
    async with ControlledClient() as http:
        await send_heartbeat(
            context,
            Heartbeat(monitor="health", run_id="run-1", url=url),
            http,
        )
    assert route.called
    assert audit.rows == ["ok"]
    assert EGRESS_ALLOWLIST == frozenset({"uptime.betterstack.com", "us.i.posthog.com"})


async def test_dry_run_heartbeat_makes_no_http_call() -> None:
    context, audit = write_context(dry_run=True)
    async with ControlledClient() as http:
        await send_heartbeat(
            context,
            Heartbeat(
                monitor="health",
                run_id="run-1",
                url=f"https://{BETTERSTACK_HOST}/heartbeat/synthetic",
            ),
            http,
        )
    assert audit.rows == ["skipped"]
