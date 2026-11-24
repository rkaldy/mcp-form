import asyncio
import sqlite3
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import aiosqlite
import pytest
from pytest_mock import MockerFixture

from form.database import DatabasePool, QueryResult, SQLValue, Statement
from form.database.d1 import D1Binding, D1Pool
from form.database.sqlite import SQLitePool


@pytest.fixture
async def sqlite_pool(tmp_path: Path) -> SQLitePool:
    """Provide an isolated real SQLite database with no application schema."""
    pool = SQLitePool(tmp_path / "nested" / "adapter.sqlite")
    async with pool.connection() as connection:
        await connection.execute(
            "CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT UNIQUE)"
        )
    return pool


@pytest.mark.anyio
async def test_sqlite_persists_parameterized_writes_across_scopes(
    sqlite_pool: SQLitePool,
):
    """Persist bound values without SQL interpolation or an explicit commit."""
    pool: DatabasePool = sqlite_pool
    value = "a quote ' and SQL-like text ; DELETE FROM records"
    async with pool.connection() as connection:
        result = await connection.execute(
            "INSERT INTO records (value) VALUES (?) RETURNING id", (value,)
        )
        assert result == QueryResult([{"id": 1}], 1)

    async with pool.connection() as connection:
        assert await connection.fetch_one(
            "SELECT id, value FROM records WHERE id = ?1", (1,)
        ) == {"id": 1, "value": value}
        assert await connection.fetch_all("SELECT id FROM records ORDER BY id") == [
            {"id": 1}
        ]
        assert (
            await connection.fetch_one("SELECT id FROM records WHERE id = ?", (9,))
            is None
        )
        assert (
            await connection.fetch_all("SELECT id FROM records WHERE id = ?", (9,))
            == []
        )


@pytest.mark.anyio
async def test_connection_scope_does_not_imply_a_transaction(sqlite_pool: SQLitePool):
    """Keep earlier autocommitted writes when later application work fails."""
    with pytest.raises(RuntimeError, match="application failure"):
        async with sqlite_pool.connection() as connection:
            await connection.execute(
                "INSERT INTO records (value) VALUES (?)", ("kept",)
            )
            raise RuntimeError("application failure")

    async with sqlite_pool.connection() as connection:
        assert await connection.fetch_one("SELECT value FROM records") == {
            "value": "kept"
        }


@pytest.mark.anyio
async def test_sqlite_batch_is_atomic_and_preserves_result_order(
    sqlite_pool: SQLitePool,
):
    """Run a successful batch in order and roll back every write in a failed batch."""
    async with sqlite_pool.connection() as connection:
        results = await connection.batch(
            [
                Statement("INSERT INTO records (value) VALUES (?)", ("first",)),
                Statement("SELECT value FROM records ORDER BY id"),
            ]
        )
        assert results == [QueryResult([], 1), QueryResult([{"value": "first"}], 0)]
        with pytest.raises(sqlite3.IntegrityError):
            await connection.batch(
                [
                    Statement(
                        "INSERT INTO records (value) VALUES (?)", ("rolled back",)
                    ),
                    Statement("INSERT INTO records (value) VALUES (?)", ("first",)),
                ]
            )
        assert await connection.fetch_all("SELECT value FROM records ORDER BY id") == [
            {"value": "first"}
        ]
        assert await connection.batch([]) == []
        # The same connection remains usable after a rolled-back batch.
        assert (
            await connection.execute("INSERT INTO records(value) VALUES ('next')")
        ).changes == 1


@pytest.mark.anyio
async def test_sqlite_enforces_foreign_keys(sqlite_pool: SQLitePool):
    """Match D1's foreign-key enforcement on each newly opened SQLite connection."""
    async with sqlite_pool.connection() as connection:
        await connection.execute(
            "CREATE TABLE children (parent_id INTEGER REFERENCES records(id))"
        )
        with pytest.raises(sqlite3.IntegrityError):
            await connection.execute("INSERT INTO children VALUES (?)", (100,))


@pytest.mark.anyio
async def test_sqlite_preserves_conflict_error_after_automatic_rollback(
    sqlite_pool: SQLitePool,
):
    """Preserve the constraint error when SQLite has already rolled back a batch."""
    async with sqlite_pool.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            await connection.batch(
                [
                    Statement("INSERT INTO records(value) VALUES (?)", ("same",)),
                    Statement(
                        "INSERT OR ROLLBACK INTO records(value) VALUES (?)", ("same",)
                    ),
                ]
            )
        assert await connection.fetch_all("SELECT * FROM records") == []


@pytest.mark.anyio
@pytest.mark.parametrize("paused_sql", ["BEGIN", "COMMIT"])
async def test_sqlite_cancelled_batch_finishes_before_connection_reuse(
    sqlite_pool: SQLitePool, mocker: MockerFixture, paused_sql: str
):
    """Preserve cancellation and a usable connection after a pending transaction call."""
    reached = asyncio.Event()
    release = asyncio.Event()
    execute = aiosqlite.Connection.execute

    @asynccontextmanager
    async def gated_execute(
        database: aiosqlite.Connection,
        sql: str,
        parameters: Sequence[SQLValue] = (),
    ) -> AsyncIterator[aiosqlite.Cursor]:
        async with execute(database, sql, parameters) as cursor:
            if sql == paused_sql:
                reached.set()
                await release.wait()
            yield cursor

    async with sqlite_pool.connection() as connection:
        mocker.patch.object(aiosqlite.Connection, "execute", gated_execute)
        task = asyncio.create_task(
            connection.batch(
                [Statement("INSERT INTO records(value) VALUES (?)", ("first",))]
            )
        )
        await asyncio.wait_for(reached.wait(), timeout=2)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        assert await connection.fetch_all("SELECT value FROM records") == [
            {"value": "first"}
        ]
        await connection.batch(
            [Statement("INSERT INTO records(value) VALUES (?)", ("next",))]
        )
        assert len(await connection.fetch_all("SELECT * FROM records")) == 2


@pytest.fixture
def d1_jsnull(mocker: MockerFixture) -> object:
    """Model Pyodide's JavaScript-null sentinel without importing its runtime."""
    sentinel = object()
    mocker.patch(
        "form.database.d1.import_module", return_value=SimpleNamespace(jsnull=sentinel)
    )
    return sentinel


@pytest.fixture
def d1_binding(mocker: MockerFixture, d1_jsnull: object) -> Mock:
    """Represent the documented D1 binding and asynchronous statement API."""
    binding = mocker.create_autospec(D1Binding, instance=True)
    statement = binding.prepare.return_value
    statement.bind.return_value = statement
    statement.run = mocker.AsyncMock()
    return binding


def result_proxy(rows: list[dict[str, object]], changes: int = 0) -> SimpleNamespace:
    """Emulate JsProxy.to_py rather than returning a raw Python dictionary."""
    return SimpleNamespace(
        to_py=lambda: {"success": True, "results": rows, "meta": {"changes": changes}}
    )


@pytest.mark.anyio
async def test_d1_binds_values_and_converts_javascript_results(
    d1_binding: Mock, d1_jsnull: object
):
    """Bind scalars through D1 and expose plain dictionaries to CRUD callers."""
    statement = d1_binding.prepare.return_value
    statement.run.return_value = result_proxy([{"id": 1, "value": d1_jsnull}], 1)
    pool: DatabasePool = D1Pool(d1_binding)
    async with pool.connection() as connection:
        result = await connection.execute("SELECT ?1 AS id, ?2 AS value", (True, None))
    assert result == QueryResult([{"id": 1, "value": None}], 1)
    d1_binding.prepare.assert_called_once_with("SELECT ?1 AS id, ?2 AS value")
    statement.bind.assert_called_once_with(1, d1_jsnull)
    statement.run.assert_awaited_once_with()


@pytest.mark.anyio
async def test_d1_fetches_rows_and_returns_none_when_empty(d1_binding: Mock):
    """Expose first/all rows and consistent empty results without binding no values."""
    statement = d1_binding.prepare.return_value
    statement.run.side_effect = [
        result_proxy([{"id": 1}, {"id": 2}]),
        result_proxy([{"id": 1}, {"id": 2}]),
        result_proxy([]),
    ]
    async with D1Pool(d1_binding).connection() as connection:
        assert await connection.fetch_one("SELECT id FROM records") == {"id": 1}
        assert await connection.fetch_all("SELECT id FROM records") == [
            {"id": 1},
            {"id": 2},
        ]
        assert await connection.fetch_one("SELECT id FROM records WHERE 0") is None
    statement.bind.assert_not_called()


@pytest.mark.anyio
async def test_d1_batch_uses_one_atomic_binding_call(
    d1_binding: Mock, mocker: MockerFixture
):
    """Submit the complete ordered batch to D1 instead of autocommitting a loop."""
    first = mocker.Mock()
    second = mocker.Mock()
    first.bind.return_value = first
    d1_binding.prepare.side_effect = [first, second]
    d1_binding.batch.return_value = [result_proxy([], 1), result_proxy([{"id": 1}])]
    async with D1Pool(d1_binding).connection() as connection:
        results = await connection.batch(
            [
                Statement("INSERT INTO records VALUES (?)", (1,)),
                Statement("SELECT id FROM records"),
            ]
        )
        assert await connection.batch([]) == []
    assert results == [QueryResult([], 1), QueryResult([{"id": 1}], 0)]
    d1_binding.batch.assert_awaited_once_with([first, second])
    first.run.assert_not_called()
    second.run.assert_not_called()


@pytest.mark.anyio
async def test_d1_propagates_failures_without_retry(d1_binding: Mock):
    """Preserve a provider failure and avoid issuing a write more than once."""
    error = RuntimeError("synthetic provider failure")
    statement = d1_binding.prepare.return_value
    statement.run.side_effect = error
    async with D1Pool(d1_binding).connection() as connection:
        with pytest.raises(RuntimeError) as caught:
            await connection.execute("INSERT INTO records VALUES (?)", (1,))
    assert caught.value is error
    statement.run.assert_awaited_once()


@pytest.mark.anyio
async def test_d1_preserves_unsuccessful_result_error(d1_binding: Mock):
    """Never report a returned unsuccessful D1 result as a successful write."""
    d1_binding.prepare.return_value.run.return_value = SimpleNamespace(
        to_py=lambda: {"success": False, "error": "synthetic query failure"}
    )
    async with D1Pool(d1_binding).connection() as connection:
        with pytest.raises(RuntimeError, match="synthetic query failure"):
            await connection.execute("INSERT INTO records VALUES (?)", (1,))
