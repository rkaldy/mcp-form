import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from sqlite3 import Connection
from typing import Annotated

from fastapi import Depends

from form.settings import Settings, get_settings


class Database:
    def __init__(self, settings: Settings):
        self.db_file = settings.database_path

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        conn = sqlite3.connect(self.db_file, autocommit=True)
        try:
            yield conn
        finally:
            conn.close()


def get_database(settings: Annotated[Settings, Depends(get_settings)]):
    return Database(settings)
