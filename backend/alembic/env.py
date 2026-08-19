"""Alembic migration environment for PennyPilot.

The application owns the SQLAlchemy metadata, so migrations and runtime use
the same model definitions. Importing ``app.models`` here is important: it
registers every mapped table before Alembic evaluates ``target_metadata``.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.db import Base

# Register all model classes with Base.metadata. Keep this as a module import
# rather than importing individual classes so new models are picked up by
# ``alembic revision --autogenerate``.
import app.models  # noqa: F401,E402


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _set_database_url() -> None:
    """Use the same URL resolution as the application itself."""

    # ConfigParser treats '%' as interpolation syntax. Escaping it here keeps
    # passwords containing a percent sign valid in an Alembic run.
    url = get_settings().database_url.replace("%", "%%")
    config.set_main_option("sqlalchemy.url", url)


def run_migrations_offline() -> None:
    _set_database_url()
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    _set_database_url()
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
