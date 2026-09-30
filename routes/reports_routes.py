"""
General Ledger v0.2.0
File: routes/reports_routes.py
Description: Reports pages and JSON API. Phase 1: trial balance. P&L, balance sheet,
             GL detail and the tax summary arrive in phase 3.
"""

from datetime import date

from flask import Blueprint, redirect, render_template, request

from routes.api import envelope
from utils import reports
from utils.money import parse_optional_date

reports_bp = Blueprint("reports", __name__)


@reports_bp.route("/reports")
def reports_index():
    return redirect("/reports/trial-balance")


@reports_bp.route("/reports/trial-balance")
def trial_balance_page():
    return render_template("reports_trial_balance.html")


@reports_bp.route("/api/reports/trial-balance", methods=["GET"])
@envelope
def trial_balance():
    as_of = parse_optional_date(request.args.get("as_of"), "As-of date") or date.today()
    return {"report": reports.trial_balance(as_of)}

""" EOF - reports_routes.py """
