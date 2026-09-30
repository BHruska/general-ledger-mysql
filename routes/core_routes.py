"""
General Ledger v0.1.0
File: routes/core_routes.py
Description: Health check, the status API, and the Dashboard shell. Real dashboard
             figures arrive with the core ledger (phase 1).
"""

import logging

from flask import Blueprint, jsonify, render_template

import config
import db
from utils import credentials

core_bp = Blueprint("core", __name__)

log = logging.getLogger(__name__)


@core_bp.route("/healthz")
def healthz():
    """Liveness only -- deliberately no login, no database call, no third-party call.

    Docker runs this from inside the container every 30s. If it touched MySQL or
    Plaid, their outage would mark this container unhealthy and send an operator
    looking in the wrong place. Dependency status is /api/status, which a person reads.
    """
    return jsonify({"success": True, "status": "ok", "version": config.APP_VERSION})


@core_bp.route("/api/status")
def status():
    """Dependency status for the Dashboard. Reports; never decides."""
    session_secret = credentials.describe(config.SESSION_SECRET_REF)
    return jsonify(
        {
            "success": True,
            "version": config.APP_VERSION,
            "database": "ok" if db.ping() else "unreachable",
            # Where the signing key came from and how strongly it is held -- never the key.
            "session_secret": {
                "source": session_secret["source"],
                "weak": session_secret["weak"],
                "fingerprint": session_secret["fingerprint"],
            },
            "https": config.APP_HTTPS,
        }
    )


@core_bp.route("/")
def dashboard_page():
    return render_template("dashboard.html")

""" EOF - core_routes.py """
