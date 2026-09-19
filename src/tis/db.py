"""Small async Psycopg pool wrapper for fixed, parameterized service queries."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any, Protocol

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

STATEMENT_TIMEOUT_MS = 10_000


class Database(Protocol):
    """Minimal database contract consumed by state and audit stores."""

    async def execute(self, query: str, parameters: Sequence[Any]) -> None:
        """Execute a fixed parameterized statement in a transaction."""

    async def fetch_one(self, query: str, parameters: Sequence[Any]) -> Mapping[str, Any] | None:
        """Fetch one mapping from a fixed parameterized statement."""

    async def fetch_value(self, query: str, parameters: Sequence[Any]) -> Any:
        """Fetch the first value from a fixed parameterized statement."""

    async def fetch_all(self, query: str, parameters: Sequence[Any]) -> list[Mapping[str, Any]]:
        """Fetch all mappings from a fixed parameterized statement."""


async def _configure(connection: AsyncConnection[dict[str, Any]]) -> None:
    await connection.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")


class PsycopgDatabase:
    """Own an async pool; opening and queries affect the configured PostgreSQL database."""

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 5) -> None:
        self.pool: AsyncConnectionPool[AsyncConnection[dict[str, Any]]] = AsyncConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            open=False,
            kwargs={"autocommit": False, "row_factory": dict_row},
            configure=_configure,
        )

    async def open(self) -> None:
        """Open database pool connections."""
        await self.pool.open()

    async def close(self) -> None:
        """Close database pool connections."""
        await self.pool.close()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        """Yield a transactional connection and roll back automatically on failure."""
        async with self.pool.connection() as connection:
            async with connection.transaction():
                yield connection

    async def execute(self, query: str, parameters: Sequence[Any]) -> None:
        """Execute a fixed parameterized statement and commit on success."""
        async with self.connection() as connection:
            await connection.execute(query, parameters)

    async def fetch_one(self, query: str, parameters: Sequence[Any]) -> Mapping[str, Any] | None:
        """Fetch one row from a fixed parameterized statement."""
        async with self.connection() as connection:
            cursor = await connection.execute(query, parameters)
            return await cursor.fetchone()

    async def fetch_value(self, query: str, parameters: Sequence[Any]) -> Any:
        """Fetch the first column of one row from a fixed parameterized statement."""
        row = await self.fetch_one(query, parameters)
        return next(iter(row.values())) if row else None

    async def fetch_all(self, query: str, parameters: Sequence[Any]) -> list[Mapping[str, Any]]:
        """Fetch all rows from a fixed parameterized statement."""
        async with self.connection() as connection:
            cursor = await connection.execute(query, parameters)
            return list(await cursor.fetchall())
