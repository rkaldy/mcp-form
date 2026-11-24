import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import URL


def test_session_database_is_migrated(sqlite_database: sqlite3.Connection):
    """The shared database starts at the current migration head before test writes."""
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert heads
    revisions = sqlite_database.execute(
        "SELECT version_num FROM alembic_version"
    ).fetchall()
    assert {row[0] for row in revisions} == set(heads)
    assert not sqlite_database.in_transaction


def test_migrations_upgrade_and_downgrade(tmp_path: Path):
    """Apply the migration chain, check metadata, and reverse it on a fresh database."""
    path = tmp_path / "migration.sqlite"
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    url = URL.create("sqlite", database=str(path)).render_as_string(hide_password=False)
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))

    command.upgrade(config, "head")
    command.check(config)
    command.downgrade(config, "base")
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute("SELECT version_num FROM alembic_version").fetchall()
            == []
        )
    command.upgrade(config, "head")
    command.check(config)
