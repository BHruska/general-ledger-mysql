"""
General Ledger v0.3.0
File: routes/banking_routes.py
Description: Banking pages (Review, Import file, Connections) and their JSON API. The
             web process makes no outbound call here: file import is an upload.
"""

from flask import Blueprint, redirect, render_template, request

from routes.api import body, envelope
from utils import bank_accounts, bank_queue
from utils.errors import LedgerError
from utils.feeds import file_import

banking_bp = Blueprint("banking", __name__)


@banking_bp.route("/banking")
def banking_index():
    return redirect("/banking/review")


@banking_bp.route("/banking/review")
def review_page():
    return render_template("banking_review.html")


@banking_bp.route("/banking/import")
def import_page():
    return render_template("banking_import.html")


@banking_bp.route("/banking/connections")
def connections_page():
    return render_template("banking_connections.html")


# ---------------------------------------------------------------- feed accounts

@banking_bp.route("/api/banking/accounts", methods=["GET"])
@envelope
def list_accounts():
    return {"accounts": bank_accounts.list_bank_accounts(),
            "eligible_gl_accounts": bank_accounts.eligible_gl_accounts()}


@banking_bp.route("/api/banking/accounts", methods=["POST"])
@envelope
def create_account():
    return {"account": bank_accounts.create_file_account(body())}


@banking_bp.route("/api/banking/accounts/<int:bank_account_id>", methods=["PATCH"])
@envelope
def update_account(bank_account_id):
    return {"account": bank_accounts.update_bank_account(bank_account_id, body())}


@banking_bp.route("/api/banking/accounts/<int:bank_account_id>", methods=["DELETE"])
@envelope
def delete_account(bank_account_id):
    bank_accounts.delete_bank_account(bank_account_id)
    return {}


# ---------------------------------------------------------------- file import

def _upload() -> tuple[int, str, str | None]:
    data = body()
    content = data.get("content")
    if not isinstance(content, str) or not content:
        raise LedgerError("Choose a file.")
    try:
        bank_account_id = int(data.get("bank_account_id"))
    except (TypeError, ValueError):
        raise LedgerError("Choose the account this file belongs to.") from None
    return bank_account_id, content, data.get("filename")


@banking_bp.route("/api/banking/import/preview", methods=["POST"])
@envelope
def import_preview():
    bank_account_id, content, _ = _upload()
    return {"preview": file_import.preview(bank_account_id, content)}


@banking_bp.route("/api/banking/import", methods=["POST"])
@envelope
def import_file():
    bank_account_id, content, filename = _upload()
    return {"result": file_import.import_file(bank_account_id, content, filename)}


# ---------------------------------------------------------------- review queue

@banking_bp.route("/api/banking/lines", methods=["GET"])
@envelope
def list_lines():
    return bank_queue.list_lines(request.args.get("view", "review"),
                                 request.args.get("bank_account_id", type=int))


@banking_bp.route("/api/banking/lines/<int:txn_id>/check", methods=["POST"])
@envelope
def check_line(txn_id):
    return {"check": bank_queue.check_post(txn_id, body())}


@banking_bp.route("/api/banking/lines/<int:txn_id>/post", methods=["POST"])
@envelope
def post_line(txn_id):
    return bank_queue.post_line(txn_id, body())


@banking_bp.route("/api/banking/lines/<int:txn_id>/exclude", methods=["POST"])
@envelope
def exclude_line(txn_id):
    return bank_queue.exclude(txn_id, body().get("reason"))


@banking_bp.route("/api/banking/lines/<int:txn_id>/restore", methods=["POST"])
@envelope
def restore_line(txn_id):
    return bank_queue.restore(txn_id)


@banking_bp.route("/api/banking/lines/<int:txn_id>/unpost", methods=["POST"])
@envelope
def unpost_line(txn_id):
    return bank_queue.unpost(txn_id)

""" EOF - banking_routes.py """
