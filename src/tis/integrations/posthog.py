"""Guarded server-side PostHog event capture."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from tis.guards import WriteContext, external_write
from tis.http import ControlledClient
from tis.log import correlation_id


class CaptureEvent(BaseModel):
    """Strict outgoing PostHog capture payload with no personal-data fields."""

    model_config = ConfigDict(extra="ignore")

    event: str
    external_id: str | None = None
    properties: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


def _event_key(event: CaptureEvent, *_args: Any, **_kwargs: Any) -> str:
    return f"{event.event}:{event.external_id or correlation_id()}"


@external_write(source="posthog", action="capture", key=_event_key)
async def capture(
    context: WriteContext,
    event: CaptureEvent,
    http: ControlledClient,
    *,
    api_key: str,
    host: HttpUrl,
) -> None:
    """Send one guarded, non-personal PostHog event."""
    payload = {
        "api_key": api_key,
        "event": event.event,
        "distinct_id": event.external_id or correlation_id(),
        "properties": event.properties,
    }
    await http.request("POST", f"{str(host).rstrip('/')}/capture", json=payload)
