"""
General Ledger v0.6.0
File: routes/reports_routes.py
Description: Reports pages and JSON API, plus a CSV of the same rows for the accountant
             (docs/DESIGN.md section 9): P&L, balance sheet, trial balance, GL detail,
             account list, bank transactions.
"""

import csv
import io
from datetime import date

from flask import Blueprint, Response, redirect, render_template, request

from routes.api import envelope
from utils import reports, statements
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
    return redirect("/reports/profit-and-loss")


@reports_bp.route("/reports/profit-and-loss")
def pnl_page():
    return render_template("reports_pnl.html")


@reports_bp.route("/reports/balance-sheet")
def balance_sheet_page():
    return render_template("reports_balance_sheet.html")


@reports_bp.route("/reports/gl-detail")
def gl_detail_page():
    return render_template("reports_gl_detail.html")


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


# ---------------------------------------------------------------- profit and loss

def _pnl_args():
    start, end = _range()
    return start, end, request.args.get("compare", "none")


@reports_bp.route("/api/reports/profit-and-loss", methods=["GET"])
@envelope
def pnl():
    return {"report": statements.profit_and_loss(*_pnl_args())}


def _statement_rows(sections, width):
    """Flatten statement sections into CSV rows: section label, account lines, total."""
    out = []
    for sec in sections:
        out.append([sec["label"]] + [""] * width)
        for r in sec["rows"]:
            name = ("    " if r["depth"] else "") + f'{r["number"]} {r["name"]}'
            out.append(["", name] + ([""] * len(r["amounts"]) if r["is_header"] else r["amounts"]))
        out.append([f'Total {sec["label"]}', ""] + sec["total"])
    return out


@reports_bp.route("/api/reports/profit-and-loss.csv", methods=["GET"])
def pnl_csv():
    try:
        r = statements.profit_and_loss(*_pnl_args())
    except LedgerError as e:
        return _csv_error(e)
    cols = [f'{c["start"]} to {c["end"]}' for c in r["columns"]]
    by_key = {sec["key"]: sec for sec in r["sections"]}
    rows = _statement_rows([by_key["income"], by_key["cogs"]], len(cols))
    rows.append(["Gross Profit", ""] + r["gross_profit"])
    rows += _statement_rows([by_key["expenses"]], len(cols))
    rows.append(["Net Operating Income", ""] + r["net_operating_income"])
    rows += _statement_rows([by_key["other_income"], by_key["other_expense"]], len(cols))
    rows.append(["Net Other Income", ""] + r["net_other_income"])
    rows.append(["Net Income", ""] + r["net_income"])
    return _csv(f'profit-and-loss-{r["start"]}-to-{r["end"]}.csv', ["Section", "Account"] + cols, rows)


# ---------------------------------------------------------------- balance sheet

def _bs_args():
    return _as_of(), request.args.get("compare", "none")


@reports_bp.route("/api/reports/balance-sheet", methods=["GET"])
@envelope
def balance_sheet():
    return {"report": statements.balance_sheet(*_bs_args())}


@reports_bp.route("/api/reports/balance-sheet.csv", methods=["GET"])
def balance_sheet_csv():
    try:
        r = statements.balance_sheet(*_bs_args())
    except LedgerError as e:
        return _csv_error(e)
    cols = [c["as_of"] for c in r["columns"]]
    rows = _statement_rows([s for s in r["sections"] if s["key"] != "equity"], len(cols))
    equity = next(s for s in r["sections"] if s["key"] == "equity")
    rows.append(["Equity"] + [""] * len(cols))
    for row in equity["rows"]:
        rows.append(["", ("    " if row["depth"] else "") + f'{row["number"]} {row["name"]}']
                    + ([""] * len(cols) if row["is_header"] else row["amounts"]))
    rows.append(["", "Net Income"] + r["net_income"])
    rows.append(["Total Equity", ""] + r["total_equity"])
    rows.append(["Total Assets", ""] + r["total_assets"])
    rows.append(["Total Liabilities and Equity", ""] + r["total_liabilities_and_equity"])
    return _csv(f'balance-sheet-{r["as_of"]}.csv', ["Section", "Account"] + cols, rows)


# ---------------------------------------------------------------- general ledger detail

def _gl_args():
    start, end = _range()
    return start, end, request.args.get("account_id", type=int)


@reports_bp.route("/api/reports/gl-detail", methods=["GET"])
@envelope
def gl_detail():
    return {"report": statements.gl_detail(*_gl_args())}


@reports_bp.route("/api/reports/gl-detail.csv", methods=["GET"])
def gl_detail_csv():
    try:
        r = statements.gl_detail(*_gl_args())
    except LedgerError as e:
        return _csv_error(e)
    rows = []
    for a in r["accounts"]:
        acct = f'{a["number"]} {a["name"]}'
        rows.append([acct, r["start"], "", "", "Opening balance", "", "", "", "", a["opening"]])
        for l in a["lines"]:
            rows.append([acct, l["entry_date"], l["entry_id"], l["source"], l["memo"], l["payee"], l["split"],
                         l["debit"], l["credit"], l["balance"]])
        rows.append([acct, r["end"], "", "", "Closing balance", "", "", a["total_debit"], a["total_credit"],
                     a["closing"]])
    return _csv(f'gl-detail-{r["start"]}-to-{r["end"]}.csv',
                ["Account", "Date", "Entry", "Source", "Memo", "Payee", "Split", "Debit", "Credit", "Balance"], rows)

""" EOF - reports_routes.py """
