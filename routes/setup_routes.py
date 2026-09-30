"""
General Ledger v0.2.0
File: routes/setup_routes.py
Description: Setup pages (Accounts, Settings) and their JSON API. Payees, Rules and
             Health join the sub-menu with phases 2 and 6.
"""

from flask import Blueprint, redirect, render_template, request

from routes.api import body, envelope
from utils import accounts, payees, rules, settings_manager

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


@setup_bp.route("/setup/payees")
def payees_page():
    return render_template("setup_payees.html")


@setup_bp.route("/api/payees", methods=["GET"])
@envelope
def list_payees():
    return payees.list_payees(request.args.get("view", "active"))


@setup_bp.route("/api/payees/<int:payee_id>", methods=["PATCH"])
@envelope
def update_payee(payee_id):
    return {"payee": payees.update_payee(payee_id, body())}


@setup_bp.route("/api/payees/archive-unused", methods=["POST"])
@envelope
def archive_unused():
    return payees.archive_unused(body())


@setup_bp.route("/setup/rules")
def rules_page():
    return render_template("setup_rules.html")


@setup_bp.route("/api/rules", methods=["GET"])
@envelope
def list_rules():
    return rules.list_rules()


@setup_bp.route("/api/rules", methods=["POST"])
@envelope
def create_rule():
    return {"rule": rules.create_rule(body())}


@setup_bp.route("/api/rules/<int:rule_id>", methods=["PATCH"])
@envelope
def update_rule(rule_id):
    return {"rule": rules.update_rule(rule_id, body())}


@setup_bp.route("/api/rules/<int:rule_id>", methods=["DELETE"])
@envelope
def delete_rule(rule_id):
    rules.delete_rule(rule_id)
    return {}


@setup_bp.route("/api/rules/preview", methods=["POST"])
@envelope
def preview_rule():
    return {"preview": rules.preview_pattern(body())}


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
