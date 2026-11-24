"""Local SQLite implementation; imported only when a local pool is needed."""

import asyncio
import sqlite3
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

import aiosqlite

from form.database import DatabaseConnection, QueryResult, Row, SQLValue, Statement


class SQLiteConnection:
    def __init__(self, connection: aiosqlite.Connection):
        self._connection = connection
        self._lock = asyncio.Lock()

    async def execute(
        self, sql: str, parameters: Sequence[SQLValue] = ()
    ) -> QueryResult:
        async with self._lock:
            return await self._execute(sql, parameters)

    async def _execute(self, sql: str, parameters: Sequence[SQLValue]) -> QueryResult:
        async with self._connection.execute(sql, parameters) as cursor:
            rows = await cursor.fetchall()
            # sqlite3.Row values are SQLite scalars on this portable SQL surface.
            result_rows = [cast(Row, dict(row)) for row in rows]
            return QueryResult(result_rows, max(cursor.rowcount, 0))

    async def fetch_one(
        self, sql: str, parameters: Sequence[SQLValue] = ()
    ) -> Row | None:
        rows = (await self.execute(sql, parameters)).rows
        return rows[0] if rows else None

    async def fetch_all(
        self, sql: str, parameters: Sequence[SQLValue] = ()
    ) -> list[Row]:
        return (await self.execute(sql, parameters)).rows

    async def batch(self, statements: Sequence[Statement]) -> list[QueryResult]:
        if not statements:
            return []
        async with self._lock:
            # A cancelled aiosqlite await does not stop its queued SQL. Keep the
            # complete transaction alive and drain it before releasing this scope.
            task = asyncio.create_task(self._batch(statements))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                    except sqlite3.Error:
                        break
                if not task.cancelled():
                    task.exception()
                raise

    async def _batch(self, statements: Sequence[Statement]) -> list[QueryResult]:
        # D1 batches are atomic; an explicit internal transaction gives local
        # SQLite the same contract without exposing commit/rollback to CRUDs.
        try:
            await self._execute("BEGIN", ())
            results = [
                await self._execute(statement.sql, statement.parameters)
                for statement in statements
            ]
            await self._execute("COMMIT", ())
            return results
        except sqlite3.Error, asyncio.CancelledError:
            # SQLite conflict policies can already have rolled the batch back.
            if self._connection.in_transaction:
                await self._execute("ROLLBACK", ())
            raise


class SQLitePool:
    """Open a separate asynchronous connection per scope; create parent dirs lazily."""

    def __init__(self, path: str | Path = "data/form.sqlite"):
        self._path = Path(path)

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[DatabaseConnection]:
        await asyncio.to_thread(self._path.parent.mkdir, parents=True, exist_ok=True)
        async with aiosqlite.connect(self._path, autocommit=True) as connection:
            connection.row_factory = aiosqlite.Row
            async with connection.execute("PRAGMA foreign_keys = ON"):
                pass
            yield SQLiteConnection(connection)
