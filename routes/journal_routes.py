"""
General Ledger v0.2.0
File: routes/journal_routes.py
Description: Journal pages (Entries, New entry, Registers) and their JSON API. The math
             and every posting rule live in utils/journal.py and utils/reports.py.
"""

from flask import Blueprint, render_template, request

from routes.api import body, envelope
from utils import journal, reports
from utils.money import parse_optional_date

journal_bp = Blueprint("journal", __name__)


def _range():
    start = parse_optional_date(request.args.get("start"), "Start date")
    end = parse_optional_date(request.args.get("end"), "End date")
    default_start, default_end = reports.default_range()
    return start or default_start, end or default_end


@journal_bp.route("/journal")
def entries_page():
    return render_template("journal_entries.html")


@journal_bp.route("/journal/new")
def new_entry_page():
    return render_template("journal_new.html")


@journal_bp.route("/journal/registers")
def registers_page():
    return render_template("journal_register.html")


@journal_bp.route("/api/journal/entries", methods=["GET"])
@envelope
def list_entries():
    start, end = _range()
    return {"start": start.isoformat(), "end": end.isoformat(),
            "entries": journal.list_entries(start, end)}


@journal_bp.route("/api/journal/entries/<int:entry_id>", methods=["GET"])
@envelope
def get_entry(entry_id):
    return {"entry": journal.get_entry(entry_id)}


@journal_bp.route("/api/journal/validate", methods=["POST"])
@envelope
def validate():
    return {"check": journal.validate(body())}


@journal_bp.route("/api/journal/entries", methods=["POST"])
@envelope
def create_entry():
    return {"entry": journal.create_manual(body())}


@journal_bp.route("/api/journal/entries/<int:entry_id>/replace", methods=["POST"])
@envelope
def replace_entry(entry_id):
    return journal.replace_manual(entry_id, body())


@journal_bp.route("/api/journal/entries/<int:entry_id>/reverse", methods=["POST"])
@envelope
def reverse_entry(entry_id):
    return {"entry": journal.reverse(entry_id, body())}


@journal_bp.route("/api/journal/entries/<int:entry_id>/memo", methods=["PATCH"])
@envelope
def set_memo(entry_id):
    return {"entry": journal.set_memo(entry_id, body().get("memo"))}


@journal_bp.route("/api/journal/register", methods=["GET"])
@envelope
def register():
    account_id = request.args.get("account_id", type=int)
    if account_id is None:
        return {"register": None}
    start, end = _range()
    return {"register": reports.account_register(account_id, start, end)}

""" EOF - journal_routes.py """
