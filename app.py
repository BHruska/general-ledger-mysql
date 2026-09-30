"""
General Ledger v0.1.0
File: app.py
Description: Flask entry point - registers blueprints and the shared top-nav list.
"""

import logging
from datetime import timedelta

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

import config
from routes.auth_routes import auth_bp
from routes.core_routes import core_bp
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

# The ONE definition of the top nav. Major sections only - do not add entries
# without the owner's explicit approval. docs/DESIGN.md section 12.1 proposes six;
# only Dashboard exists until they are approved and built.
NAV_ITEMS = [
    {"key": "dashboard", "label": "Dashboard", "url": "/"},
]


@app.context_processor
def inject_nav():
    return {"NAV_ITEMS": NAV_ITEMS, "APP_VERSION": config.APP_VERSION,
            "APP_TITLE_PREFIX": config.APP_TITLE_PREFIX}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)

""" EOF - app.py """
