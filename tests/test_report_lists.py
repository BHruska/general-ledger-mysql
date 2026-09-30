"""
General Ledger v0.3.2
File: tests/test_report_lists.py
Description: Account List and Bank Transactions reports, and the CSV downloads.
"""

import csv
import io
from datetime import date
from decimal import Decimal
from pathlib import Path

import db
from utils import bank_accounts, bank_queue, journal, reports
from utils.feeds import file_import
from utils.journal import LineInput

CARD_CSV = (Path(__file__).resolve().parent / "fixtures" / "chase_card.csv").read_text()


def post(entry_date, *pairs):
    with db.SessionLocal.begin() as session:
        journal.post_entry(session, entry_date=entry_date,
                           lines=[LineInput(a, Decimal(x)) for a, x in pairs])


def card_feed(chart) -> int:
    ba = bank_accounts.create_file_account({"gl_account_id": chart["2010"], "name": "Card", "mask": "3052",
                                            "feed_start_date": "2026-07-01"})["id"]
    file_import.import_file(ba, CARD_CSV, None)
    return ba


def test_account_list_has_every_account_in_normal_direction(chart):
    post(date(2026, 3, 1), (chart["6110"], "20"), (chart["6120"], "30"), (chart["2010"], "-50"))
    r = reports.account_list(date(2026, 6, 30))
    rows = {x["number"]: x for x in r["rows"]}
    assert len(rows) == len(chart)                       # zero balances included
    assert rows["2010"]["balance"] == "50.00"            # owed, shown positive
    assert rows["6100"]["is_header"] and rows["6100"]["balance"] == "50.00"
    assert rows["6110"]["full_name"] == "Software:Hosting"
    assert rows["3000"]["balance"] == "0.00"
    assert r["counts"]["EXPENSE"] == 4


def test_account_list_agrees_with_trial_balance(chart):
    post(date(2025, 6, 1), (chart["1010"], "1000"), (chart["4000"], "-1000"))
    post(date(2026, 2, 1), (chart["6300"], "40"), (chart["1010"], "-40"))
    al = {x["number"]: x["balance"] for x in reports.account_list(date(2026, 6, 30))["rows"]}
    tb = {x["number"]: x for x in reports.trial_balance(date(2026, 6, 30))["rows"]}
    assert al["3900"] == tb["3900"]["credit"] == "1000.00"   # prior-year income, computed
    assert al["1010"] == tb["1010"]["debit"] == "960.00"
    assert al["4000"] == "0.00" and "4000" not in tb


def test_account_list_shows_feed(chart):
    card_feed(chart)
    rows = {x["number"]: x for x in reports.account_list(date(2026, 9, 30))["rows"]}
    assert rows["2010"]["feed"] == "Card" and rows["1010"]["feed"] is None


def test_bank_transactions_summary_and_filters(chart):
    ba = card_feed(chart)
    hosting = next(l for l in bank_queue.list_lines("review")["lines"] if l["description"] == "EXAMPLE HOSTING")
    bank_queue.post_line(hosting["id"], {"account_id": chart["6110"]})
    coffee = next(l for l in bank_queue.list_lines("review")["lines"] if l["description"] == "COFFEE SHOP")
    bank_queue.exclude(coffee["id"], "Personal, not business")

    r = reports.bank_transactions(date(2026, 7, 1), date(2026, 9, 30))
    assert len(r["rows"]) == 6
    assert r["summary"]["POSTED"] == {"count": 1, "money_in": "0.00", "money_out": "49.00"}
    assert r["summary"]["EXCLUDED"]["count"] == 1
    assert r["summary"]["NEW"] == {"count": 4, "money_in": "2083.75", "money_out": "25.00"}
    posted = next(x for x in r["rows"] if x["status"] == "POSTED")
    assert posted["posted_to"] == "6110 Hosting"

    only_posted = reports.bank_transactions(date(2026, 7, 1), date(2026, 9, 30), ba, "POSTED")
    assert [x["description"] for x in only_posted["rows"]] == ["EXAMPLE HOSTING"]
    assert only_posted["summary"]["NEW"]["count"] == 4   # the summary always covers every status


def test_csv_downloads(signed_in, chart):
    card_feed(chart)
    for path, first_col in (("/api/reports/account-list.csv?as_of=2026-09-30", "Number"),
                            ("/api/reports/trial-balance.csv?as_of=2026-09-30", "Number"),
                            ("/api/reports/bank-transactions.csv?start=2026-07-01&end=2026-09-30", "Date")):
        resp = signed_in.get(path)
        assert resp.status_code == 200, path
        assert resp.mimetype == "text/csv" and "attachment" in resp.headers["Content-Disposition"]
        rows = list(csv.reader(io.StringIO(resp.get_data(as_text=True))))
        assert rows[0][0] == first_col
    bank_rows = list(csv.reader(io.StringIO(signed_in.get(
        "/api/reports/bank-transactions.csv?start=2026-07-01&end=2026-09-30").get_data(as_text=True))))
    assert len(bank_rows) == 7 and bank_rows[1][4] == "-20.00"
    bad = signed_in.get("/api/reports/bank-transactions.csv?start=2026-09-30&end=2026-07-01")
    assert bad.status_code == 400


def test_csv_requires_login(client):
    assert client.get("/api/reports/account-list.csv").status_code == 401


def test_report_pages_render(signed_in):
    for path in ("/reports/accounts", "/reports/bank-transactions", "/reports/trial-balance"):
        assert signed_in.get(path).status_code == 200, path

""" EOF - test_report_lists.py """
