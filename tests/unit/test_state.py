"""Integration state and kill-switch cache tests."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from tis.state import StateStore


class FakeDatabase:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {"kill_switch": {"on": False}}
        self.reads = 0
        self.executions: list[tuple[str, Sequence[Any]]] = []

    async def fetch_one(self, query: str, parameters: Sequence[Any]) -> Mapping[str, Any] | None:
        self.reads += 1
        value = self.values.get(str(parameters[0]))
        return {"value": value} if value is not None else None

    async def fetch_value(self, query: str, parameters: Sequence[Any]) -> Any:
        return None

    async def execute(self, query: str, parameters: Sequence[Any]) -> None:
        self.executions.append((query, parameters))
        self.values[str(parameters[0])] = parameters[1]


async def test_kill_switch_cache_expires_within_fifteen_seconds() -> None:
    database = FakeDatabase()
    now = [0.0]
    state = StateStore(database, clock=lambda: now[0])
    assert await state.kill_switch_on() is False
    database.values["kill_switch"] = {"on": True}
    now[0] = 14.9
    assert await state.kill_switch_on() is False
    now[0] = 15.0
    assert await state.kill_switch_on() is True
    assert database.reads == 2


async def test_set_uses_fixed_parameterized_sql() -> None:
    database = FakeDatabase()
    state = StateStore(database)
    await state.set("synthetic", {"value": 1})
    query, parameters = database.executions[0]
    assert "%s" in query
    assert "synthetic" not in query
    assert parameters == ("synthetic", {"value": 1})


async def test_last_run_is_stored_in_utc() -> None:
    database = FakeDatabase()
    state = StateStore(database)
    stamp = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    await state.mark_last_run("fixture", stamp)
    assert database.values["last_run:fixture"] == {"at": "2026-01-02T03:04:00+00:00"}
