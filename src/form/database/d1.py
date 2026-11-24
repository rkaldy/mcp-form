"""Cloudflare D1 binding adapter without imports of local SQLite dependencies."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from importlib import import_module
from typing import NotRequired, Protocol, TypedDict

from form.database import DatabaseConnection, QueryResult, Row, SQLValue, Statement


class _Metadata(TypedDict):
    changes: int


class _ResultData(TypedDict):
    success: bool
    results: list[dict[str, object]]
    meta: _Metadata
    error: NotRequired[str]


class D1Result(Protocol):
    """D1's JsProxy result, converted at the Python/JavaScript boundary."""

    def to_py(self) -> _ResultData: ...


class D1PreparedStatement(Protocol):
    def bind(self, *parameters: object) -> D1PreparedStatement: ...

    async def run(self) -> D1Result: ...


class D1Binding(Protocol):
    """The subset of ``env.DB`` used by this adapter."""

    def prepare(self, sql: str) -> D1PreparedStatement: ...

    async def batch(
        self, statements: list[D1PreparedStatement]
    ) -> Sequence[D1Result]: ...


def _js_null() -> object:
    # Pyodide maps Python None to JS undefined, whereas D1 requires JS null.
    # Import lazily so local SQLite needs neither Pyodide nor its runtime SDK.
    return import_module("pyodide.ffi").jsnull


def _value(value: object, js_null: object) -> SQLValue:
    if value is js_null or value is None:
        return None
    if isinstance(value, str | int | float):
        return value
    raise TypeError("D1 returned a value outside the portable SQL scalar types")


def _result(result: D1Result) -> QueryResult:
    data = result.to_py()
    if not data["success"]:
        # D1 normally rejects the promise on SQL errors. A failed result must not
        # be treated as a successful write if the binding returns one instead.
        raise RuntimeError(
            data.get("error", "D1 returned an unsuccessful query result")
        )
    js_null = _js_null()
    rows = [
        {key: _value(value, js_null) for key, value in row.items()}
        for row in data["results"]
    ]
    return QueryResult(rows, data["meta"]["changes"])


class D1Connection:
    def __init__(self, binding: D1Binding):
        self._binding = binding

    def _prepare(self, sql: str, parameters: Sequence[SQLValue]) -> D1PreparedStatement:
        statement = self._binding.prepare(sql)
        # bool is an int subtype in Python, but D1 binding rejects JS booleans.
        values = tuple(
            _js_null()
            if value is None
            else int(value)
            if isinstance(value, bool)
            else value
            for value in parameters
        )
        return statement.bind(*values) if values else statement

    async def execute(
        self, sql: str, parameters: Sequence[SQLValue] = ()
    ) -> QueryResult:
        return _result(await self._prepare(sql, parameters).run())

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
        prepared = [
            self._prepare(statement.sql, statement.parameters)
            for statement in statements
        ]
        return [_result(result) for result in await self._binding.batch(prepared)]


class D1Pool:
    """Use an injected Worker binding; no physical connection or transaction is opened."""

    def __init__(self, binding: D1Binding):
        self._binding = binding

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[DatabaseConnection]:
        yield D1Connection(self._binding)
