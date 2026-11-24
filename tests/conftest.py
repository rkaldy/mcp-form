"""Transactional SQLite fixtures for testing CRUDs through the D1 adapter.

This binding is test-only: real D1 autocommits and cannot roll back a whole test.
"""

import asyncio
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL

from form.database.d1 import D1Connection, D1Result, SQLValue


class _SQLiteStatement:
    def __init__(
        self,
        connection: sqlite3.Connection,
        sql: str,
        parameters: tuple[SQLValue, ...] = (),
    ):
        self._connection = connection
        self._sql = sql
        self._parameters = parameters

    def bind(self, *parameters: SQLValue) -> _SQLiteStatement:
        return _SQLiteStatement(self._connection, self._sql, parameters)

    async def run(self) -> D1Result:
        return await asyncio.to_thread(self._run)

    def _run(self) -> D1Result:
        cursor = self._connection.execute(self._sql, self._parameters)
        try:
            rows = [dict(row) for row in cursor.fetchall()]
            return {
                "success": True,
                "results": rows,
                "meta": {"changes": max(cursor.rowcount, 0)},
            }
        finally:
            cursor.close()


class _SQLiteBinding:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    def prepare(self, sql: str) -> _SQLiteStatement:
        return _SQLiteStatement(self._connection, sql)


@pytest.fixture(scope="session")
def sqlite_database(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[sqlite3.Connection]:
    """Migrate one isolated database to head per session before opening test scopes."""
    path = tmp_path_factory.mktemp("database") / "test.sqlite"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    url = URL.create("sqlite", database=str(path)).render_as_string(hide_password=False)
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    connection = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def db_connection(sqlite_database: sqlite3.Connection) -> Iterator[D1Connection]:
    """Give each test a transaction and roll it back even when the test fails."""
    sqlite_database.execute("BEGIN")
    try:
        yield D1Connection(_SQLiteBinding(sqlite_database))
    finally:
        sqlite_database.rollback()
