"""Async database pool configuration tests."""

from contextlib import asynccontextmanager
from typing import Any, cast

import pytest

import tis.db
from tis.db import STATEMENT_TIMEOUT_MS, PsycopgDatabase


class FakePool:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.opened = False
        self.closed = False

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True


async def test_pool_is_lazy_transactional_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tis.db, "AsyncConnectionPool", FakePool)
    database = PsycopgDatabase("postgresql://synthetic.invalid/db", min_size=2, max_size=4)
    pool = database.pool
    assert isinstance(pool, FakePool)
    assert pool.kwargs["open"] is False
    assert pool.kwargs["min_size"] == 2
    assert pool.kwargs["max_size"] == 4
    assert pool.kwargs["kwargs"]["autocommit"] is False
    await database.open()
    await database.close()
    assert pool.opened and pool.closed


async def test_connection_configuration_sets_ten_second_timeout() -> None:
    queries: list[str] = []

    class Connection:
        async def execute(self, query: str) -> None:
            queries.append(query)

    await tis.db._configure(Connection())  # type: ignore[arg-type]  # verifies callback contract
    assert queries == [f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}"]


async def test_query_failure_exits_transaction_with_rollback_signal() -> None:
    exits: list[type[BaseException] | None] = []

    class Transaction:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(
            self,
            error_type: type[BaseException] | None,
            _error: BaseException | None,
            _traceback: object,
        ) -> None:
            exits.append(error_type)

    class Connection:
        def transaction(self) -> Transaction:
            return Transaction()

        async def execute(self, query: str, parameters: object) -> None:
            raise RuntimeError("synthetic database failure")

    class Pool:
        @asynccontextmanager
        async def connection(self) -> Any:
            yield Connection()

    database = PsycopgDatabase("postgresql://synthetic.invalid/db")
    database.pool = cast(Any, Pool())
    with pytest.raises(RuntimeError, match="synthetic database failure"):
        await database.execute("SELECT %s", (1,))
    assert exits == [RuntimeError]
