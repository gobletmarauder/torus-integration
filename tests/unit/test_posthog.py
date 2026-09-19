"""PostHog integration tests."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from pydantic import HttpUrl
from respx import MockResponse

from tis.guards import WriteContext
from tis.http import ControlledClient
from tis.integrations.posthog import CaptureEvent, capture

POSTHOG_HOST = "us.i.posthog.com"


class State:
    async def kill_switch_on(self) -> bool:
        return False


class Audit:
    def __init__(self) -> None:
        self.ids: list[str] = []

    async def status(self, source: str, external_id: str, action: str) -> str | None:
        self.ids.append(external_id)
        return None

    async def successful_today(self, source: str, action: str, since: datetime) -> int:
        return 0

    async def claim(self, source: str, external_id: str, action: str) -> bool:
        self.ids.append(external_id)
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
        return None


async def test_capture_sends_modeled_payload_and_stable_key(respx_mock: object) -> None:
    route = respx_mock.post(f"https://{POSTHOG_HOST}/capture").mock(  # type: ignore[attr-defined]
        return_value=MockResponse(200)
    )
    audit = Audit()
    context = WriteContext(
        dry_run=False,
        state=State(),  # type: ignore[arg-type]
        audit=audit,
        per_run_budgets={("posthog", "capture"): 25},
        per_day_budgets={("posthog", "capture"): 200},
    )
    event = CaptureEvent(event="lead_sync", external_id="synthetic-id", ignored="discarded")
    async with ControlledClient() as http:
        await capture(
            context,
            event,
            http,
            api_key="synthetic-key",
            host=HttpUrl(f"https://{POSTHOG_HOST}"),
        )
    assert route.called
    assert audit.ids == ["lead_sync:synthetic-id"]
    payload = route.calls[0].request.content.decode()
    assert "ignored" not in payload
