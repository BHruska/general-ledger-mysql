"""
General Ledger v0.1.0
File: config.py
Description: Environment-driven configuration. Nothing environment-specific is baked
             into the image, so every value here comes from the environment or from
             a file under /etc/general-ledger.
"""

import os
from pathlib import Path


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


# Required. The entrypoint refuses to start without it, so a missing value here
# means someone is running outside the container.
DATABASE_URL = os.getenv("DATABASE_URL", "")

# nginx terminates TLS in production; dev has neither TLS nor the perimeter password.
APP_HTTPS = _flag("APP_HTTPS")


def _default_secrets_dir() -> Path:
    """Where file-shaped credentials live, for whichever context is running.

    /etc/general-ledger is the CONTAINER path, supplied by a read-only mount. Using it
    as the default everywhere made trade-portfolio's credential CLI, run natively on
    Windows, write to C:/etc/... -- somewhere the container can never read.
    """
    if Path("/.dockerenv").exists():
        return Path("/etc/general-ledger")
    return Path(__file__).resolve().parent / ".devsecrets"


SECRETS_DIR = Path(os.getenv("SECRETS_DIR") or _default_secrets_dir())

# Invoice PDFs and receipt attachments (phases 2 and 5). The only writable path in
# the image; everything else is in MySQL.
DATA_DIR = Path(os.getenv("APP_HOME", "/data"))

# The Flask session cookie is signed with this credential. Forging the cookie is a
# full login, so it is Acting-class (docs/CREDENTIALS.md section 1).
SESSION_SECRET_REF = "session_secret"

# docs/DESIGN.md section 11: the session ends after 12 hours without a request.
SESSION_IDLE_HOURS = 12

# Shorter than this is refused by manage.py set-password.
MIN_PASSWORD_LENGTH = 12

WORKER_TICK_SECONDS = int(os.getenv("WORKER_TICK_SECONDS", "15"))

# MySQL releases this if the connection dies, which is why the worker must stop
# acting the moment it loses the holding connection (docs/DESIGN.md section 2.1).
WORKER_LOCK_NAME = "general-ledger-worker"

APP_NAME = "General Ledger"
# Every browser tab title starts with this (docs/STYLING.md section 3): "Ledger - <page>".
APP_TITLE_PREFIX = "Ledger"
APP_VERSION = "0.4.2"

""" EOF - config.py """
