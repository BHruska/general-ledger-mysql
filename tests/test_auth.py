"""
General Ledger v0.1.0
File: tests/test_auth.py
Description: The owner login and the request guard (docs/DESIGN.md section 11).
"""

from urllib.parse import parse_qs, urlsplit

from sqlalchemy import text

import db
from utils import auth


def test_healthz_needs_no_login(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_page_redirects_to_login_with_next(client):
    resp = client.get("/?tab=x")
    assert resp.status_code == 302
    location = urlsplit(resp.headers["Location"])
    assert location.path == "/login"
    assert parse_qs(location.query) == {"next": ["/?tab=x"]}


def test_api_answers_401_envelope(client):
    resp = client.get("/api/status")
    assert resp.status_code == 401
    assert resp.get_json() == {"success": False, "error": "Not signed in."}


def test_login_page_is_public(client):
    assert client.get("/login").status_code == 200


def test_login_refused_while_no_password_set(client):
    resp = client.post("/api/auth/login", json={"password": "anything at all"})
    assert resp.status_code == 401
    assert "set-password" in resp.get_json()["error"]


def test_wrong_password_refused(client, owner_password):
    resp = client.post("/api/auth/login", json={"password": owner_password + "x"})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Wrong password."
    assert client.get("/api/status").status_code == 401


def test_sign_in_reaches_pages_and_api(signed_in):
    assert signed_in.get("/").status_code == 200
    data = signed_in.get("/api/status").get_json()
    assert data["success"] is True
    assert data["database"] == "ok"
    # Where the key came from, never the key.
    assert "test-only" not in str(data)


def test_state_change_requires_json(signed_in):
    # A cross-site form post can only send form encodings; this is the CSRF defence.
    resp = signed_in.post("/api/auth/logout", data={"x": "1"})
    assert resp.status_code == 415
    assert signed_in.get("/api/status").status_code == 200


def test_login_itself_requires_json(client, owner_password):
    resp = client.post("/api/auth/login", data={"password": owner_password})
    assert resp.status_code == 415


def test_logout_ends_session(signed_in):
    assert signed_in.post("/api/auth/logout", json={}).status_code == 200
    assert signed_in.get("/api/status").status_code == 401


def test_password_change_signs_out_existing_sessions(signed_in):
    auth.set_password("a completely different passphrase")
    assert signed_in.get("/api/status").status_code == 401


def test_next_is_same_site_only(client, owner_password):
    for evil in ("//evil.example/x", "https://evil.example/", "/\\evil.example"):
        resp = client.post(f"/api/auth/login?next={evil}", json={"password": owner_password})
        assert resp.get_json()["next"] == "/", evil
    resp = client.post("/api/auth/login?next=/journal", json={"password": owner_password})
    assert resp.get_json()["next"] == "/journal"


def test_short_password_rejected():
    try:
        auth.set_password("short")
    except auth.AuthError:
        return
    raise AssertionError("a short password was accepted")


def test_password_stored_as_argon2id_hash(owner_password):
    with db.engine.connect() as conn:
        stored = conn.execute(text("SELECT owner_password_hash FROM settings WHERE id = 1")).scalar()
    assert stored.startswith("$argon2id$")
    assert owner_password not in stored


def test_session_cookie_flags(app, signed_in):
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Strict"
    assert app.permanent_session_lifetime.total_seconds() == 12 * 3600


def test_settings_holds_one_row():
    with db.engine.connect() as conn:
        try:
            conn.execute(text("INSERT INTO settings (id, company_name) VALUES (2, 'x')"))
        except Exception:
            return
    raise AssertionError("a second settings row was accepted")

""" EOF - test_auth.py """
