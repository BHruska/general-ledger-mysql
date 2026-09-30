"""
General Ledger v0.2.0
File: routes/setup_routes.py
Description: Setup pages (Accounts, Settings) and their JSON API. Payees, Rules and
             Health join the sub-menu with phases 2 and 6.
"""

from flask import Blueprint, redirect, render_template

from routes.api import body, envelope
from utils import accounts, settings_manager

setup_bp = Blueprint("setup", __name__)


@setup_bp.route("/setup")
def setup_index():
    return redirect("/setup/accounts")


@setup_bp.route("/setup/accounts")
def accounts_page():
    return render_template("setup_accounts.html")


@setup_bp.route("/setup/settings")
def settings_page():
    return render_template("setup_settings.html")


@setup_bp.route("/api/accounts", methods=["GET"])
@envelope
def list_accounts():
    return {"accounts": accounts.list_accounts()}


@setup_bp.route("/api/accounts", methods=["POST"])
@envelope
def create_account():
    return {"account": accounts.create_account(body())}


@setup_bp.route("/api/accounts/<int:account_id>", methods=["PATCH"])
@envelope
def update_account(account_id):
    return {"account": accounts.update_account(account_id, body())}


@setup_bp.route("/api/accounts/<int:account_id>", methods=["DELETE"])
@envelope
def delete_account(account_id):
    accounts.delete_account(account_id)
    return {}


@setup_bp.route("/api/settings", methods=["GET"])
@envelope
def get_settings():
    return {"settings": settings_manager.get_settings()}


@setup_bp.route("/api/settings", methods=["PATCH"])
@envelope
def update_settings():
    return {"settings": settings_manager.update_company(body())}


@setup_bp.route("/api/settings/lock-date", methods=["POST"])
@envelope
def set_lock_date():
    return {"settings": settings_manager.set_lock_date(body())}

""" EOF - setup_routes.py """
