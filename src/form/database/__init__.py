"""Asynchronous D1 SQL contracts shared by local and hosted database bindings."""

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Protocol

type SQLValue = str | int | float | None
type Row = dict[str, SQLValue]


@dataclass(frozen=True)
class Statement:
    """One SQL statement with positional scalar parameters (``?`` or ``?1``)."""

    sql: str
    parameters: tuple[SQLValue, ...] = ()


@dataclass(frozen=True)
class QueryResult:
    rows: list[Row] = field(default_factory=list)
    changes: int = 0


class DatabaseConnection(Protocol):
    """A resource scope, not an interactive transaction.

    Statements autocommit individually. Use batch for atomic multi-statement work.
    Backend exceptions propagate unchanged; the adapter never retries SQL.
    """

    async def execute(
        self, sql: str, parameters: Sequence[SQLValue] = ()
    ) -> QueryResult: ...

    async def fetch_one(
        self, sql: str, parameters: Sequence[SQLValue] = ()
    ) -> Row | None: ...

    async def fetch_all(
        self, sql: str, parameters: Sequence[SQLValue] = ()
    ) -> list[Row]: ...

    async def batch(self, statements: Sequence[Statement]) -> list[QueryResult]:
        """Run the whole sequence atomically, returning results in input order."""
        ...


class DatabasePool(Protocol):
    """Provide short-lived connection scopes to application services."""

    def connection(self) -> AbstractAsyncContextManager[DatabaseConnection]: ...
