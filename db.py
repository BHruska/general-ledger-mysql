"""
General Ledger v0.1.0
File: db.py
Description: SQLAlchemy engine and session factory. One engine per process.
"""

import logging

from sqlalchemy import create_engine, event, text
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.orm import DeclarativeBase, sessionmaker

import config

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Declarative base for every model. Alembic autogenerate reads its metadata."""


def utc_timestamp():
    """DATETIME(6), UTC, every time.

    `fsp` is a MySQL-dialect argument -- sa.DateTime(fsp=6) raises TypeError. Defined
    once here so no model can reach for the generic type and silently lose precision.
    """
    return MySQLDateTime(fsp=6)


def build_engine(url: str | None = None, **kwargs):
    """Engine with the two settings a long-idle MySQL client cannot do without.

    MySQL closes idle connections after wait_timeout (8h) and the worker idles
    overnight between daily syncs, so a pooled connection is routinely dead by
    morning. pool_pre_ping turns that into a transparent reconnect.
    """
    engine = create_engine(
        url or config.DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=3600,
        future=True,
        **kwargs,
    )

    @event.listens_for(engine, "connect")
    def _set_session_timezone(dbapi_connection, _record):
        # TZ in the env file is for log readability only; it must never reach stored
        # data. Every DATETIME(6) in this schema is UTC. Accounting dates are DATE and
        # have no time zone at all.
        with dbapi_connection.cursor() as cur:
            cur.execute("SET time_zone = '+00:00'")

    return engine


engine = build_engine() if config.DATABASE_URL else None
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True) if engine else None


def ping() -> bool:
    """Cheap liveness check for the status panel. Not used by /healthz -- see routes."""
    if engine is None:
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        log.exception("database ping failed")
        return False

""" EOF - db.py """
