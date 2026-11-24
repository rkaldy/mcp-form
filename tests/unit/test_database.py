import sqlite3
from unittest.mock import Mock

import pytest
from fastapi import Request
from pytest_mock import MockerFixture

from form.database.d1 import D1Binding, D1Connection, D1Result, QueryResult, Row
from form.database.dependencies import get_database_binding


@pytest.fixture
def d1_binding(mocker: MockerFixture) -> Mock:
    """Represent the documented D1 binding and asynchronous statement API."""
    binding = mocker.create_autospec(D1Binding, instance=True)
    statement = binding.prepare.return_value
    statement.bind.return_value = statement
    statement.run = mocker.AsyncMock()
    return binding


def result_data(rows: list[Row], changes: int = 0) -> D1Result:
    """Represent the Python dictionaries returned by the official Workers SDK."""
    return {"success": True, "results": rows, "meta": {"changes": changes}}


@pytest.mark.anyio
async def test_d1_binds_values_and_converts_javascript_results(d1_binding: Mock):
    """Bind scalars through D1 and expose plain dictionaries to CRUD callers."""
    statement = d1_binding.prepare.return_value
    statement.run.return_value = result_data([{"id": 1, "value": None}], 1)
    connection = D1Connection(d1_binding)
    result = await connection.execute("SELECT ?1 AS id, ?2 AS value", (True, None))
    assert result == QueryResult([{"id": 1, "value": None}], 1)
    d1_binding.prepare.assert_called_once_with("SELECT ?1 AS id, ?2 AS value")
    statement.bind.assert_called_once_with(1, None)
    statement.run.assert_awaited_once_with()


@pytest.mark.anyio
async def test_d1_fetches_rows_and_returns_none_when_empty(d1_binding: Mock):
    """Expose first/all rows and consistent empty results without binding no values."""
    statement = d1_binding.prepare.return_value
    statement.run.side_effect = [
        result_data([{"id": 1}, {"id": 2}]),
        result_data([{"id": 1}, {"id": 2}]),
        result_data([]),
    ]
    connection = D1Connection(d1_binding)
    assert await connection.fetch_one("SELECT id FROM records") == {"id": 1}
    assert await connection.fetch_all("SELECT id FROM records") == [
        {"id": 1},
        {"id": 2},
    ]
    assert await connection.fetch_one("SELECT id FROM records WHERE 0") is None
    statement.bind.assert_not_called()


@pytest.mark.anyio
async def test_d1_propagates_failures_without_retry(d1_binding: Mock):
    """Preserve a provider failure and avoid issuing a write more than once."""
    error = RuntimeError("synthetic provider failure")
    statement = d1_binding.prepare.return_value
    statement.run.side_effect = error
    connection = D1Connection(d1_binding)
    with pytest.raises(RuntimeError) as caught:
        await connection.execute("INSERT INTO records VALUES (?)", (1,))
    assert caught.value is error
    statement.run.assert_awaited_once()


@pytest.mark.anyio
async def test_d1_preserves_unsuccessful_result_error(d1_binding: Mock):
    """Never report a returned unsuccessful D1 result as a successful write."""
    d1_binding.prepare.return_value.run.return_value = {
        "success": False,
        "error": "synthetic query failure",
    }
    connection = D1Connection(d1_binding)
    with pytest.raises(RuntimeError, match="synthetic query failure"):
        await connection.execute("INSERT INTO records VALUES (?)", (1,))


def test_database_dependency_requires_worker_environment():
    """Explain how to run the app when no Workers binding environment is present."""
    with pytest.raises(RuntimeError, match="pywrangler dev"):
        get_database_binding(Request({"type": "http"}))


@pytest.mark.anyio
@pytest.mark.parametrize("sql_failure", [False, True])
async def test_db_connection_fixture_rolls_back(
    request: pytest.FixtureRequest,
    sqlite_database: sqlite3.Connection,
    sql_failure: bool,
):
    """Verify fixture teardown removes writes and DDL and leaves no transaction open."""

    def verify_rollback():
        assert not sqlite_database.in_transaction
        assert (
            sqlite_database.execute(
                "SELECT name FROM sqlite_master WHERE name = 'fixture_records'"
            ).fetchone()
            is None
        )

    # Register before requesting the connection so this runs after its teardown.
    request.addfinalizer(verify_rollback)
    connection: D1Connection = request.getfixturevalue("db_connection")
    await connection.execute(
        "CREATE TABLE fixture_records (id INTEGER PRIMARY KEY, value TEXT)"
    )
    result = await connection.execute(
        "INSERT INTO fixture_records (value) VALUES (?) RETURNING id, value", ("test",)
    )
    assert result == QueryResult([{"id": 1, "value": "test"}], 1)
    assert await connection.fetch_one(
        "SELECT value FROM fixture_records WHERE id = ?", (1,)
    ) == {"value": "test"}
    if sql_failure:
        with pytest.raises(sqlite3.IntegrityError):
            await connection.execute(
                "INSERT INTO fixture_records (id, value) VALUES (?, ?)",
                (1, "duplicate"),
            )
