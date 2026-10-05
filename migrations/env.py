"""Alembic environment (PL-2).

Reads the database URL from AgentFox settings rather than alembic.ini, so a migration
run always targets the same database the application does. A migration tool that can
be pointed somewhere else by accident is a way to lose data.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from agentfox.core.config import get_settings
from agentfox.core.models import Base

config = context.config
if config.config_file_name is not None:
    # `disable_existing_loggers=False` is load-bearing. The default is True, which
    # switches off every logger already configured — including all of AgentFox's. The
    # effect is that after any migration or stamp (and `init_db` stamps), the platform
    # stops emitting warnings entirely: provider degradation, fail-open decisions and
    # tenancy bypasses all go silent. For a product whose whole argument is that
    # controls must not quietly stop reporting, that is not an acceptable default.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite cannot ALTER most things in place; batch mode rewrites the table.
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
