"""Migrated SQLite database with a rollback scope for each test."""

import os
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from sqlite3 import Connection

import pytest
from _pytest.tmpdir import TempPathFactory
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import URL

from form.settings import Settings
from tests.database import TestDatabase


def pytest_sessionstart(session: pytest.Session):
    # LiteLLM otherwise downloads pricing metadata when imported during collection.
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"


@pytest.fixture(scope="session")
def settings(tmp_path_factory: TempPathFactory) -> Settings:
    return Settings(
        target_spreadsheet="https://docs.google.com/spreadsheets/d/synthetic-test",
        database_path=tmp_path_factory.mktemp("database") / "form.sqlite3",
        images_path=tmp_path_factory.mktemp("images"),
        llm_model="test",
        llm_api_key=SecretStr("synthetic-key"),
        llm_reasoning_effort=None,
        llm_timeout=120,
        max_upload_size_bytes=20 * 1024 * 1024,
        confidence_threshold=75,
        session_ttl=timedelta(hours=24),
    )


@pytest.fixture(scope="session")
def create_database(settings: Settings):
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    url = URL.create("sqlite", database=str(settings.database_path)).render_as_string(
        hide_password=False
    )
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")


@pytest.fixture
def database(create_database, settings: Settings) -> Iterator[TestDatabase]:
    db = TestDatabase(settings)
    yield db
    db.connection.rollback()
    db.connection.close()


@pytest.fixture
def db_conn(database: TestDatabase) -> Iterator[Connection]:
    with database.connect() as conn:
        yield conn
