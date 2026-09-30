"""
General Ledger v0.1.0
File: tests/conftest.py
Description: Tests run against the dev stack's MySQL test database -- never another
             engine (NEW-APP-INTEGRATION.md section 2). The real migrations build it;
             each test starts from a reset settings row.

    docker compose -f compose.dev.yml up -d db
    python -m pytest
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "mysql+pymysql://gl:devpass@127.0.0.1:3308/gl_test"
)
# The suite truncates and rewrites tables. Pointing it at anything but a *_test
# database would do that to real books.
if not TEST_DATABASE_URL.rsplit("/", 1)[-1].split("?")[0].endswith("_test"):
    raise RuntimeError(f"Refusing to run tests against {TEST_DATABASE_URL}: not a *_test database.")

# Set before config/db/app are imported, since they read the environment at import.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["GL_CRED_SESSION_SECRET"] = "test-only-session-secret-not-used-anywhere-else"
# A value from the developer's shell or keyring must not leak into the tests.
os.environ["SECRETS_DIR"] = str(ROOT / "tests" / ".no-secrets")
os.environ.pop("APP_HTTPS", None)
# Attachments are written under /data in the container; tests get a throwaway directory.
os.environ["APP_HOME"] = tempfile.mkdtemp(prefix="gl-test-data-")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

import db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    yield


# A small known chart, rebuilt before every test. number: (name, type, parent number)
TEST_CHART = {
    "1010": ("Checking", "ASSET", None),
    "1200": ("Accounts Receivable", "ASSET", None),
    "2010": ("Card", "LIABILITY", None),
    "3000": ("Owner's Equity", "EQUITY", None),
    "3900": ("Retained Earnings", "EQUITY", None),
    "4000": ("Revenue", "INCOME", None),
    "6100": ("Software", "EXPENSE", None),
    "6110": ("Hosting", "EXPENSE", "6100"),
    "6120": ("SaaS", "EXPENSE", "6100"),
    "6300": ("Travel", "EXPENSE", None),
}

# Accounts a bank feed can post to.
TEST_BANK_ACCOUNTS = {"1010", "2010"}

RESET_TABLES = ("invoice_payment", "invoice_line", "invoice", "attachment", "bank_txn", "payee_rule", "bank_account", "bank_connection", "journal_line",
                "journal_entry", "audit_log", "payee", "account")

# The immutability triggers forbid DELETE on these, so they are TRUNCATEd -- which skips
# triggers, and is the only reason the suite can reset them at all.
TRIGGER_GUARDED = {"journal_line", "journal_entry"}


@pytest.fixture(autouse=True)
def chart(migrated_database):
    """Empty books with TEST_CHART, a clean settings row, and no lock date.

    Returns {account number: id}.

    Only tables a test actually dirtied are cleared, and with DELETE wherever triggers
    allow: on Docker Desktop a TRUNCATE rebuilds the table and syncs it to disk, about
    0.1 s each, while a DELETE of a few rows is about a millisecond. Truncating all ten
    tables before every test was most of the suite's run time. Ids therefore keep
    counting up between tests; tests use the ids fixtures return, never literals.
    """
    ids = {}
    with db.engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in RESET_TABLES:
            if not conn.execute(text(f"SELECT EXISTS(SELECT 1 FROM {table})")).scalar():
                continue
            verb = "TRUNCATE TABLE" if table in TRIGGER_GUARDED else "DELETE FROM"
            conn.execute(text(f"{verb} {table}"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        for number, (name, type_, parent) in TEST_CHART.items():
            result = conn.execute(
                text("INSERT INTO account (number, name, type, parent_id, is_bank_account) "
                     "VALUES (:n, :name, :t, :p, :bank)"),
                {"n": number, "name": name, "t": type_, "p": ids.get(parent),
                 "bank": number in TEST_BANK_ACCOUNTS},
            )
            ids[number] = result.lastrowid
        conn.execute(text(
            "UPDATE settings SET company_name = '', company_address = NULL, owner_password_hash = NULL, "
            "totp_secret_ref = NULL, fiscal_year_start_month = 1, lock_date = NULL, "
            "invoice_prefix = '', next_invoice_seq = 1, zelle_recipient = NULL, zelle_display_name = NULL, "
            "default_income_account_id = NULL, "
            "ar_account_id = :ar, retained_earnings_account_id = :re WHERE id = 1"
        ), {"ar": ids["1200"], "re": ids["3900"]})
    yield ids


@pytest.fixture(autouse=True)
def fast_auth(monkeypatch):
    """Production pays these costs on purpose; tests only need the behaviour.

    - A failed login waits a second (slows password guessing); here it would just
      wait, once per failed-login test.
    - The owner password hash uses argon2-cffi's deliberately expensive defaults; the
      tests check the flow and the $argon2id$ format, not the cost.
    """
    from argon2 import PasswordHasher

    from routes import auth_routes
    from utils import auth

    monkeypatch.setattr(auth_routes, "FAILED_LOGIN_DELAY_S", 0)
    monkeypatch.setattr(auth, "_hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))


@pytest.fixture
def app():
    from app import app as flask_app

    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def owner_password():
    from utils import auth

    password = "correct horse battery staple"
    auth.set_password(password)
    return password


@pytest.fixture
def signed_in(client, owner_password):
    resp = client.post("/api/auth/login", json={"password": owner_password})
    assert resp.status_code == 200, resp.get_json()
    return client

""" EOF - conftest.py """
