from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import Request
from pytest_mock import MockerFixture

from form.database import DatabasePool, QueryResult, Row, Statement
from form.database.d1 import D1Binding, D1Pool, D1Result
from form.database.dependencies import get_database_pool


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
    pool: DatabasePool = D1Pool(d1_binding)
    async with pool.connection() as connection:
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
    d1_binding.batch.return_value = [result_data([], 1), result_data([{"id": 1}])]
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
    d1_binding.prepare.return_value.run.return_value = {
        "success": False,
        "error": "synthetic query failure",
    }
    async with D1Pool(d1_binding).connection() as connection:
        with pytest.raises(RuntimeError, match="synthetic query failure"):
            await connection.execute("INSERT INTO records VALUES (?)", (1,))


@pytest.mark.anyio
async def test_database_dependency_uses_configured_binding(d1_binding: Mock):
    """Use the DB binding selected by Wrangler without a second backend selector."""
    request = Request({"type": "http", "env": SimpleNamespace(DB=d1_binding)})
    d1_binding.prepare.return_value.run.return_value = result_data([{"id": 1}])

    pool = get_database_pool(request)

    async with pool.connection() as connection:
        assert await connection.fetch_one("SELECT id FROM records") == {"id": 1}
    d1_binding.prepare.assert_called_once_with("SELECT id FROM records")


def test_database_dependency_requires_worker_environment():
    """Explain how to run the app when no Workers binding environment is present."""
    with pytest.raises(RuntimeError, match="pywrangler dev"):
        get_database_pool(Request({"type": "http"}))
