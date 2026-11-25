import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from sqlite3 import Connection

from form.database.database import Database
from form.settings import Settings


class TestDatabase(Database):
    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.connection = sqlite3.connect(self.db_file, autocommit=False)

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        yield self.connection
