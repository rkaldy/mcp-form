"""Apply migrations to SQLite or emit SQL for the D1 binding."""

from alembic import context
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from form.database.schema import metadata


class MigrationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    database_url: str


def run_migrations_offline():
    context.configure(
        url="sqlite://",
        target_metadata=metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    url = context.config.get_main_option("sqlalchemy.url")
    if not url:
        url = MigrationSettings().database_url
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=metadata, render_as_batch=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
