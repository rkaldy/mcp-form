"""Apply migrations to the configured SQLite database."""

from alembic import context
from sqlalchemy import URL, create_engine
from sqlalchemy.pool import NullPool

from form.database.schema import metadata
from form.settings import Settings


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
        path = Settings().database_path
        path.parent.mkdir(parents=True, exist_ok=True)
        url = URL.create("sqlite", database=str(path))
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
