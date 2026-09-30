"""
General Ledger v0.2.0
File: app.py
Description: Flask entry point - registers blueprints and the shared top-nav list.
"""

import logging
from datetime import timedelta

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

import config
from routes.attachment_routes import attachment_bp
from routes.auth_routes import auth_bp
from routes.banking_routes import banking_bp
from routes.core_routes import core_bp
from routes.invoice_routes import invoice_bp
from routes.journal_routes import journal_bp
from routes.reports_routes import reports_bp
from routes.setup_routes import setup_bp
from utils import credentials

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = Flask(__name__, template_folder="templates", static_folder="static")

# Behind nginx: trust X-Forwarded-Proto/Host so url_for builds public https:// URLs.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Resolved once at import. A missing key must stop the process here -- the entrypoint
# checks first so the message is readable -- rather than fall back to a random key,
# which would differ between gunicorn workers and sign people out at random.
app.secret_key = credentials.get(config.SESSION_SECRET_REF)

# nginx owns TLS, so the cookie is only marked Secure where TLS actually exists.
# PERMANENT_SESSION_LIFETIME is enforced server-side on the signed timestamp, and
# SESSION_REFRESH_EACH_REQUEST slides it, which is the 12-hour IDLE limit.
app.config.update(
    SESSION_COOKIE_NAME="gl_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=config.APP_HTTPS,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=config.SESSION_IDLE_HOURS),
    SESSION_REFRESH_EACH_REQUEST=True,
)

app.register_blueprint(auth_bp)
app.register_blueprint(core_bp)
app.register_blueprint(banking_bp)
app.register_blueprint(attachment_bp)
app.register_blueprint(invoice_bp)
app.register_blueprint(journal_bp)
app.register_blueprint(setup_bp)
app.register_blueprint(reports_bp)

# The ONE definition of the top nav. Major sections only - do not add entries
# without the owner's explicit approval. These six are docs/DESIGN.md section 12.1,
# approved by the owner on 2026-09-29.
NAV_ITEMS = [
    {"key": "dashboard", "label": "Dashboard", "url": "/"},
    {"key": "banking", "label": "Banking", "url": "/banking"},
    {"key": "journal", "label": "Journal", "url": "/journal"},
    {"key": "invoices", "label": "Invoices", "url": "/invoices"},
    {"key": "reports", "label": "Reports", "url": "/reports"},
    {"key": "setup", "label": "Setup", "url": "/setup"},
]

# Each section's sub-menu, defined once so every page in the section shows the same
# one (docs/STYLING.md section 4). Entries join as their pages are built.
SUB_MENUS = {
    "banking": [
        {"key": "review", "label": "Review", "url": "/banking/review"},
        {"key": "import", "label": "Import file", "url": "/banking/import"},
        {"key": "connections", "label": "Connections", "url": "/banking/connections"},
    ],
    "invoices": [
        {"key": "invoices", "label": "Invoices", "url": "/invoices"},
        {"key": "customers", "label": "Customers", "url": "/invoices/customers"},
    ],
    "journal": [
        {"key": "entries", "label": "Entries", "url": "/journal"},
        {"key": "new", "label": "New entry", "url": "/journal/new"},
        {"key": "registers", "label": "Registers", "url": "/journal/registers"},
    ],
    "reports": [
        {"key": "trial-balance", "label": "Trial Balance", "url": "/reports/trial-balance"},
        {"key": "accounts", "label": "Account List", "url": "/reports/accounts"},
        {"key": "bank-transactions", "label": "Bank Transactions", "url": "/reports/bank-transactions"},
        {"key": "ar-aging", "label": "A/R Aging", "url": "/reports/ar-aging"},
    ],
    "setup": [
        {"key": "accounts", "label": "Accounts", "url": "/setup/accounts"},
        {"key": "payees", "label": "Payees", "url": "/setup/payees"},
        {"key": "rules", "label": "Rules", "url": "/setup/rules"},
        {"key": "settings", "label": "Settings", "url": "/setup/settings"},
    ],
}


@app.context_processor
def inject_nav():
    return {"NAV_ITEMS": NAV_ITEMS, "SUB_MENUS": SUB_MENUS, "APP_VERSION": config.APP_VERSION,
            "APP_TITLE_PREFIX": config.APP_TITLE_PREFIX}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)

""" EOF - app.py """
