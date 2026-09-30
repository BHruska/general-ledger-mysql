"""
General Ledger v0.3.2
File: routes/reports_routes.py
Description: Reports pages and JSON API, plus a CSV of the same rows for the accountant
             (docs/DESIGN.md section 9). Trial balance, account list, bank transactions.
             P&L, balance sheet, GL detail and the tax summary arrive in phase 3.
"""

import csv
import io
from datetime import date

from flask import Blueprint, Response, redirect, render_template, request

from routes.api import envelope
from utils import reports
from utils.errors import LedgerError
from utils.money import parse_optional_date

reports_bp = Blueprint("reports", __name__)


def _as_of() -> date:
    return parse_optional_date(request.args.get("as_of"), "As-of date") or date.today()


def _range() -> tuple[date, date]:
    default_start, default_end = reports.default_range()
    start = parse_optional_date(request.args.get("start"), "Start date") or default_start
    end = parse_optional_date(request.args.get("end"), "End date") or default_end
    return start, end


def _csv(filename: str, header: list[str], rows: list[list]) -> Response:
    """Plain values, amounts as the same strings the API returns, so the accountant's
    spreadsheet and the page can never disagree."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows([["" if v is None else v for v in row] for row in rows])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _csv_error(e: LedgerError) -> Response:
    return Response(f"Report failed: {e}\n", status=400, mimetype="text/plain")


@reports_bp.route("/reports")
def reports_index():
    return redirect("/reports/trial-balance")


@reports_bp.route("/reports/trial-balance")
def trial_balance_page():
    return render_template("reports_trial_balance.html")


@reports_bp.route("/reports/accounts")
def account_list_page():
    return render_template("reports_account_list.html")


@reports_bp.route("/reports/bank-transactions")
def bank_transactions_page():
    return render_template("reports_bank_transactions.html")


# ---------------------------------------------------------------- trial balance

@reports_bp.route("/api/reports/trial-balance", methods=["GET"])
@envelope
def trial_balance():
    return {"report": reports.trial_balance(_as_of())}


@reports_bp.route("/api/reports/trial-balance.csv", methods=["GET"])
def trial_balance_csv():
    try:
        r = reports.trial_balance(_as_of())
    except LedgerError as e:
        return _csv_error(e)
    rows = [[x["number"], x["name"], x["type"], "yes" if x["is_header"] else "", x["debit"], x["credit"]]
            for x in r["rows"]]
    rows.append(["", "Total", "", "", r["total_debit"], r["total_credit"]])
    return _csv(f"trial-balance-{r['as_of']}.csv",
                ["Number", "Account", "Type", "Header (subtotal)", "Debit", "Credit"], rows)


# ---------------------------------------------------------------- account list

@reports_bp.route("/api/reports/account-list", methods=["GET"])
@envelope
def account_list():
    return {"report": reports.account_list(_as_of())}


@reports_bp.route("/api/reports/account-list.csv", methods=["GET"])
def account_list_csv():
    try:
        r = reports.account_list(_as_of())
    except LedgerError as e:
        return _csv_error(e)
    rows = [[x["number"], x["full_name"], x["type"], x["parent_number"], "yes" if x["is_header"] else "",
             "yes" if x["is_active"] else "no", "yes" if x["is_bank_account"] else "", x["feed"],
             x["tax_line"], x["description"], x["balance"]] for x in r["rows"]]
    return _csv(f"account-list-{r['as_of']}.csv",
                ["Number", "Account", "Type", "Parent", "Header", "Active", "Bank", "Feed",
                 "Tax line", "Description", f"Balance {r['as_of']}"], rows)


# ---------------------------------------------------------------- bank transactions

def _bank_args():
    start, end = _range()
    return start, end, request.args.get("bank_account_id", type=int), request.args.get("status") or None


@reports_bp.route("/api/reports/bank-transactions", methods=["GET"])
@envelope
def bank_transactions():
    return {"report": reports.bank_transactions(*_bank_args())}


@reports_bp.route("/api/reports/bank-transactions.csv", methods=["GET"])
def bank_transactions_csv():
    try:
        r = reports.bank_transactions(*_bank_args())
    except LedgerError as e:
        return _csv_error(e)
    rows = [[x["posted_date"], x["bank_account"], x["description"], x["provider_category"], x["amount"],
             x["status"], x["posted_to"], x["entry_id"], x["excluded_reason"]] for x in r["rows"]]
    return _csv(f"bank-transactions-{r['start']}-to-{r['end']}.csv",
                ["Date", "Account", "Description", "Bank category", "Amount", "Status",
                 "Posted to", "Entry", "Excluded because"], rows)

""" EOF - reports_routes.py """
