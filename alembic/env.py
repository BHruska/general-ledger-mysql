"""
General Ledger v0.1.0
File: alembic/env.py
Description: Alembic runtime. Reads DATABASE_URL from the environment and serializes
             the upgrade with a named lock. Same shape as trade-portfolio's.
"""

import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import text

import config as app_config
import db
import models  # noqa: F401 -- imported so Base.metadata sees every table

alembic_config = context.config
# The test suite runs migrations in-process and has already configured logging;
# re-reading the ini there would silence pytest's own capture.
if alembic_config.config_file_name is not None and alembic_config.attributes.get("configure_logger", True):
    fileConfig(alembic_config.config_file_name)

log = logging.getLogger("alembic.env")

target_metadata = db.Base.metadata

# The web and worker containers both run `alembic upgrade head` at start and either
# may win the race. Two processes migrating concurrently is a corrupted schema.
MIGRATION_LOCK = "general-ledger-migrate"
MIGRATION_LOCK_TIMEOUT = 60


def _url() -> str:
    # The test suite points a migration at gl_test explicitly; everything else uses
    # the process's DATABASE_URL.
    return alembic_config.attributes.get("database_url") or app_config.DATABASE_URL


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set -- alembic has nothing to connect to.")

    connectable = db.build_engine(url)

    # The lock gets its own connection, and that is not a stylistic choice.
    #
    # Running GET_LOCK on the connection alembic then uses opens an implicit
    # transaction on it, so alembic's own begin_transaction() becomes a no-op and the
    # alembic_version INSERT is never committed -- while the CREATE TABLE, being DDL,
    # autocommits regardless. trade-portfolio found exactly that on 2026-09-20.
    lock_conn = connectable.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        got = lock_conn.execute(
            text("SELECT GET_LOCK(:name, :timeout)"),
            {"name": MIGRATION_LOCK, "timeout": MIGRATION_LOCK_TIMEOUT},
        ).scalar()
        if got != 1:
            raise RuntimeError(
                f"Could not take {MIGRATION_LOCK} within {MIGRATION_LOCK_TIMEOUT}s; "
                "another container is migrating. Retry."
            )

        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
            # Explicit: SQLAlchemy 2.0 rolls back anything uncommitted when it closes.
            connection.commit()
    finally:
        lock_conn.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": MIGRATION_LOCK})
        lock_conn.close()
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

""" EOF - alembic/env.py """
