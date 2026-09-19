"""Guarded Better Stack heartbeat delivery."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, HttpUrl

from tis.guards import WriteContext, external_write
from tis.http import ControlledClient


class Heartbeat(BaseModel):
    """Synthetic-safe heartbeat routing metadata."""

    model_config = ConfigDict(extra="ignore")

    monitor: str
    run_id: str
    url: HttpUrl


@external_write(
    source="betterstack",
    action="heartbeat",
    key=lambda heartbeat, *_args, **_kwargs: f"{heartbeat.monitor}:{heartbeat.run_id}",
)
async def send_heartbeat(
    context: WriteContext,
    heartbeat: Heartbeat,
    http: ControlledClient,
) -> None:
    """Send one guarded heartbeat to Better Stack."""
    await http.request("GET", str(heartbeat.url))
