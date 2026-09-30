"""
General Ledger v0.1.0
File: worker.py
Description: Background process. Owns every scheduled external call (docs/DESIGN.md
             section 2): feed sync, rule application, invoice email, integrity check.
             Phase 0 is the frame only -- the single-writer lock and a clean SIGTERM --
             so the jobs in section 2.1 have somewhere to land.

Run with: python -m worker   (the container's `worker` role)
"""

import logging
import signal
import sys
import threading

from sqlalchemy import text

import config
import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("worker")

_shutdown = threading.Event()


def _handle_sigterm(signum, _frame):
    # Docker sends SIGTERM and waits stop_grace_period (60s) before SIGKILL. Setting
    # the flag lets the current job finish and commit rather than die mid-write.
    log.info("Signal %s received; finishing the current job and shutting down.", signum)
    _shutdown.set()


class SingleWriterLock:
    """One worker per database, enforced in the database.

    Two workers syncing the same Plaid item would each insert the same bank lines; the
    unique key on bank_txn stops the duplicates, but this stops the race (DESIGN.md
    section 2.1). The risk is a redeploy, when the outgoing and incoming containers
    briefly overlap. MySQL releases a GET_LOCK when its connection dies, so losing the
    connection must stop the worker rather than merely be logged.

    Same class as trade-portfolio's worker.py.
    """

    def __init__(self, engine, name: str):
        self._engine = engine
        self._name = name
        self._conn = None

    def acquire(self) -> bool:
        self._conn = self._engine.connect()
        got = self._conn.execute(text("SELECT GET_LOCK(:name, 0)"), {"name": self._name}).scalar()
        if got != 1:
            self._conn.close()
            self._conn = None
            return False
        return True

    def still_held(self) -> bool:
        if self._conn is None:
            return False
        try:
            return self._conn.execute(
                text("SELECT IS_USED_LOCK(:name) = CONNECTION_ID()"), {"name": self._name}
            ).scalar() == 1
        except Exception:
            log.exception("Lost the connection holding the writer lock.")
            return False

    def release(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": self._name})
        except Exception:
            log.warning("Could not release the writer lock cleanly; the connection close will.")
        finally:
            self._conn.close()
            self._conn = None


def tick() -> None:
    """One pass over requested and scheduled work. Empty until phase 2."""


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    if db.engine is None:
        log.error("DATABASE_URL is not set.")
        return 1

    lock = SingleWriterLock(db.engine, config.WORKER_LOCK_NAME)
    # Wait for the lock rather than exit: during a redeploy the old container holds it
    # for up to its grace period, and exiting would hand the restart policy a loop.
    while not lock.acquire():
        log.info("Another worker holds %s; waiting.", config.WORKER_LOCK_NAME)
        if _shutdown.wait(config.WORKER_TICK_SECONDS):
            return 0
    log.info("Worker v%s started; holding %s.", config.APP_VERSION, config.WORKER_LOCK_NAME)

    try:
        while not _shutdown.is_set():
            if not lock.still_held():
                log.error("Writer lock lost; stopping so a single writer can take over.")
                return 1
            try:
                tick()
            except Exception:
                # One bad pass must not kill the worker; the next tick retries.
                log.exception("Worker tick failed.")
            _shutdown.wait(config.WORKER_TICK_SECONDS)
    finally:
        lock.release()
        log.info("Worker stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

""" EOF - worker.py """
