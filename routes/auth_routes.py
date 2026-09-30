"""
General Ledger v0.1.0
File: routes/auth_routes.py
Description: Owner login and logout, and the request guard every other route sits
             behind (docs/DESIGN.md section 11).
"""

import logging
import time

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from utils import auth

auth_bp = Blueprint("auth", __name__)

log = logging.getLogger(__name__)

# Reachable without a session. /healthz is the container contract
# (NEW-APP-INTEGRATION.md section 4); the login pair is how a session starts.
PUBLIC_ENDPOINTS = {"core.healthz", "auth.login_page", "auth.login", "static"}

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# A failed login waits this long before answering. One owner, so this costs nothing
# legitimate and turns an online guess into a slow one.
FAILED_LOGIN_DELAY_S = 1.0


def _error(message: str, status: int):
    return jsonify({"success": False, "error": message}), status


def _safe_next(target: str | None) -> str:
    """Only a same-site path. `//evil.example` and `https://...` are open redirects."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/"


@auth_bp.before_app_request
def guard():
    # Every state-changing request must be JSON. A cross-site HTML form can only send
    # form encodings, so this is the CSRF defence alongside SameSite=Strict.
    if request.method not in SAFE_METHODS and not request.is_json:
        return _error("State-changing requests must send application/json.", 415)

    if request.endpoint in PUBLIC_ENDPOINTS:
        return None

    epoch = session.get("epoch")
    if session.get("owner") and epoch and epoch == auth.current_epoch():
        return None

    session.clear()
    if request.path.startswith("/api/"):
        return _error("Not signed in.", 401)
    target = request.path + (f"?{request.query_string.decode()}" if request.query_string else "")
    return redirect(url_for("auth.login_page", next=target))


@auth_bp.route("/login")
def login_page():
    return render_template("login.html")


@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    password = (request.get_json(silent=True) or {}).get("password") or ""
    try:
        epoch = auth.verify_login(password)
    except auth.AuthError as e:
        log.warning("login refused from %s: %s", request.remote_addr, e)
        time.sleep(FAILED_LOGIN_DELAY_S)
        return _error(str(e), 401)

    # A fresh session, never an upgraded one: anything set before login (by anyone)
    # does not survive into the signed-in session.
    session.clear()
    session.permanent = True
    session["owner"] = True
    session["epoch"] = epoch
    log.info("owner signed in from %s", request.remote_addr)
    return jsonify({"success": True, "next": _safe_next(request.args.get("next"))})


@auth_bp.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})

""" EOF - auth_routes.py """
