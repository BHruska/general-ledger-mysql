"""
General Ledger v0.3.0
File: tests/test_bank.py
Description: Chase CSV import (docs/DESIGN.md 5.4-5.5) and the review queue (section 6).
             Fixtures are synthetic files in Chase's real layouts, including its quirks:
             the checking file's extra trailing field and its space-padded ACH text.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, text

import db
from models import BankAccount, BankTxn, JournalEntry
from utils import bank_accounts, bank_queue, journal, settings_manager
from utils.errors import LedgerError
from utils.feeds import file_import
from utils.journal import JournalError, LineInput

D = Decimal
FIXTURES = Path(__file__).resolve().parent / "fixtures"
CARD_CSV = (FIXTURES / "chase_card.csv").read_text()
CHECKING_CSV = (FIXTURES / "chase_checking.csv").read_text()
START = "2026-07-01"


@pytest.fixture(autouse=True)
def books_always_balance():
    yield
    with db.SessionLocal() as session:
        assert journal.journal_total(session) == 0


@pytest.fixture
def feeds(chart):
    card = bank_accounts.create_file_account(
        {"gl_account_id": chart["2010"], "name": "Chase Card", "mask": "3052", "feed_start_date": START})["id"]
    checking = bank_accounts.create_file_account(
        {"gl_account_id": chart["1010"], "name": "Chase Checking", "mask": "3396", "feed_start_date": START})["id"]
    return {"card": card, "checking": checking}


def txns(bank_account_id=None) -> list[BankTxn]:
    with db.SessionLocal() as session:
        stmt = select(BankTxn).order_by(BankTxn.posted_date.desc(), BankTxn.id)
        if bank_account_id:
            stmt = stmt.where(BankTxn.bank_account_id == bank_account_id)
        return session.scalars(stmt).all()


def txn_by(description_start: str) -> BankTxn:
    return next(t for t in txns() if t.description.startswith(description_start))


# ------------------------------------------------------------------ parsing

def test_card_layout_signs_and_post_date():
    parsed = file_import.parse(CARD_CSV)
    assert parsed.layout == "CHASE_CARD"
    first = parsed.rows[0]
    assert (first.posted_date, first.amount, first.provider_category) == (date(2026, 9, 27), D("-20.00"), "Office & Shipping")
    payment = next(r for r in parsed.rows if r.raw["Type"] == "Payment")
    assert payment.amount == D("2071.25") and payment.provider_category == "Payment"


def test_checking_layout_trailing_field_and_padding():
    parsed = file_import.parse(CHECKING_CSV)
    assert parsed.layout == "CHASE_CHECKING"
    assert len(parsed.rows) == 4
    ach = parsed.rows[1]
    assert "  " not in ach.description and ach.description.startswith("ORIG CO NAME:EXAMPLE TELCO ORIG ID")
    assert "          " in ach.raw_description  # the raw text is kept as received
    assert ach.amount == D("-115.98") and ach.provider_category == "ACH_DEBIT"
    assert parsed.rows[0].balance == D("11174.59")


def test_normalise_is_identity_for_chase_and_refuses_the_unknown():
    assert file_import.normalise("CHASE_CARD", D("-5.00")) == D("-5.00")
    with pytest.raises(LedgerError):
        file_import.normalise("SOMETHING_ELSE", D("1"))


@pytest.mark.parametrize("content, words", [
    ("Date,Amount\n01/01/2026,5\n", "not a Chase CSV"),
    ("", "empty"),
    (CARD_CSV.replace("-20.00", "-20.005"), "more than two decimal places"),
    (CARD_CSV.replace("09/27/2026", "2026-09-27"), "bad date"),
])
def test_unreadable_files_refused(content, words):
    with pytest.raises(LedgerError, match=words):
        file_import.parse(content)


def test_identical_rows_get_distinct_ids():
    rows = file_import.parse(CARD_CSV).rows
    file_import.assign_ids(1, rows)
    coffees = [r.external_id for r in rows if r.raw_description == "COFFEE SHOP"]
    assert len(coffees) == 2 and coffees[0] != coffees[1]
    rows_again = file_import.parse(CARD_CSV).rows
    file_import.assign_ids(1, rows_again)
    assert [r.external_id for r in rows] == [r.external_id for r in rows_again]


# ------------------------------------------------------------------ import

def test_preview_writes_nothing_and_import_adds_rows(feeds):
    p = file_import.preview(feeds["card"], CARD_CSV)
    assert (p["rows_in_file"], p["new"], p["before_start"], p["already_present"]) == (7, 6, 1, 0)
    assert p["new_total"] == str(D("-20") - 10 + D("2071.25") - 49 + D("12.50"))
    assert txns() == []
    r = file_import.import_file(feeds["card"], CARD_CSV, "card.csv")
    assert r["new"] == 6
    assert {t.status for t in txns()} == {"NEW"}


def test_reimport_and_overlap_add_nothing_twice(feeds):
    file_import.import_file(feeds["card"], CARD_CSV, "a.csv")
    again = file_import.import_file(feeds["card"], CARD_CSV, "a.csv")
    assert (again["new"], again["already_present"]) == (0, 6)
    # A later download overlapping the first: one new line, the rest recognised.
    later = CARD_CSV.replace("Memo\n", "Memo\n09/29/2026,09/29/2026,NEW CHARGE,Travel,Sale,-7.00,\n", 1)
    r = file_import.import_file(feeds["card"], later, "b.csv")
    assert (r["new"], r["already_present"]) == (1, 6)
    assert len(txns(feeds["card"])) == 7


def test_file_must_match_account_kind(feeds):
    with pytest.raises(LedgerError, match="credit card CSV"):
        file_import.preview(feeds["checking"], CARD_CSV)


def test_checking_balance_moves_forward_only(feeds):
    file_import.import_file(feeds["checking"], CHECKING_CSV, None)
    older = CHECKING_CSV.split("\n")
    older_file = "\n".join([older[0]] + older[3:])  # rows from 09/18 only, lower balance
    file_import.import_file(feeds["checking"], older_file, None)
    with db.SessionLocal() as session:
        ba = session.get(BankAccount, feeds["checking"])
        assert ba.reported_balance == D("11174.59")
        assert ba.reported_balance_at.date() == date(2026, 9, 28)


def test_feed_account_rules(chart, feeds):
    with pytest.raises(LedgerError, match="already has a feed"):
        bank_accounts.create_file_account({"gl_account_id": chart["2010"], "name": "x", "feed_start_date": START})
    with pytest.raises(LedgerError, match="not marked as a bank"):
        bank_accounts.create_file_account({"gl_account_id": chart["6300"], "name": "x", "feed_start_date": START})
    listed = {a["name"]: a for a in bank_accounts.list_bank_accounts()}
    assert listed["Chase Card"]["kind"] == "CREDIT" and listed["Chase Checking"]["kind"] == "DEPOSITORY"


# ------------------------------------------------------------------ posting

def test_post_card_charge(chart, feeds):
    file_import.import_file(feeds["card"], CARD_CSV, None)
    line = txn_by("EXAMPLE HOSTING")
    result = bank_queue.post_line(line.id, {"account_id": chart["6110"]})
    with db.SessionLocal() as session:
        entry = session.get(JournalEntry, result["entry_id"])
        assert (entry.source, entry.entry_date, entry.memo) == ("BANK", date(2026, 9, 11), "EXAMPLE HOSTING")
        # A $49 charge credits the card liability and debits the expense.
        assert {(l.account_id, l.amount) for l in entry.lines} == {(chart["2010"], D("-49.00")),
                                                                    (chart["6110"], D("49.00"))}
        posted = session.get(BankTxn, line.id)
        assert (posted.status, posted.entry_id) == ("POSTED", entry.id)


def test_post_deposit(chart, feeds):
    file_import.import_file(feeds["checking"], CHECKING_CSV, None)
    line = txn_by("Zelle payment")
    entry_id = bank_queue.post_line(line.id, {"account_id": chart["4000"]})["entry_id"]
    with db.SessionLocal() as session:
        lines = {(l.account_id, l.amount) for l in session.get(JournalEntry, entry_id).lines}
    assert lines == {(chart["1010"], D("1500.00")), (chart["4000"], D("-1500.00"))}


def test_cannot_post_twice(chart, feeds):
    file_import.import_file(feeds["card"], CARD_CSV, None)
    line = txn_by("EXAMPLE HOSTING")
    bank_queue.post_line(line.id, {"account_id": chart["6110"]})
    with pytest.raises(LedgerError, match="already posted"):
        bank_queue.post_line(line.id, {"account_id": chart["6300"]})


def test_split_must_add_up(chart, feeds):
    file_import.import_file(feeds["card"], CARD_CSV, None)
    line = txn_by("EXAMPLE HOSTING")
    short = {"splits": [{"account_id": chart["6110"], "amount": "30"}, {"account_id": chart["6120"], "amount": "10"}]}
    check = bank_queue.check_post(line.id, short)
    assert not check["ok"] and check["remaining"] == "9.00"
    with pytest.raises(JournalError, match="9.00 left to assign"):
        bank_queue.post_line(line.id, short)
    full = {"splits": [{"account_id": chart["6110"], "amount": "30"}, {"account_id": chart["6120"], "amount": "19"}]}
    assert bank_queue.check_post(line.id, full)["ok"]
    bank_queue.post_line(line.id, full)


def test_cannot_post_to_a_bank_account(chart, feeds):
    file_import.import_file(feeds["card"], CARD_CSV, None)
    line = txn_by("Payment Thank You")
    with pytest.raises(JournalError, match="own bank account"):
        bank_queue.post_line(line.id, {"account_id": chart["2010"]})
    # Posting one side of a transfer to the other bank account needs that account's line too.
    with pytest.raises(JournalError, match="do not match the bank line"):
        bank_queue.post_line(line.id, {"account_id": chart["1010"]})


def test_bank_entry_must_match_its_line(chart, feeds):
    file_import.import_file(feeds["card"], CARD_CSV, None)
    line = txn_by("EXAMPLE HOSTING")
    with pytest.raises(JournalError, match="do not match"):
        with db.SessionLocal.begin() as session:
            journal.post_entry(session, entry_date=line.posted_date, source="BANK", bank_txn_ids=[line.id],
                               lines=[LineInput(chart["2010"], D("-48.00")), LineInput(chart["6110"], D("48.00"))])


def test_lock_date_applies_to_bank_lines(chart, feeds):
    file_import.import_file(feeds["card"], CARD_CSV, None)
    settings_manager.set_lock_date({"lock_date": "2026-09-15"})
    with pytest.raises(JournalError, match="lock date"):
        bank_queue.post_line(txn_by("EXAMPLE HOSTING").id, {"account_id": chart["6110"]})


def test_exclude_needs_reason_and_restores(chart, feeds):
    file_import.import_file(feeds["card"], CARD_CSV, None)
    line = txn_by("COFFEE SHOP")
    with pytest.raises(LedgerError, match="Say why"):
        bank_queue.exclude(line.id, "  ")
    bank_queue.exclude(line.id, "Personal, not business")
    assert bank_queue.list_lines("excluded")["lines"][0]["excluded_reason"] == "Personal, not business"
    bank_queue.restore(line.id)
    assert txn_by("COFFEE SHOP").status == "NEW"


def test_unpost_reverses_and_returns_to_review(chart, feeds):
    file_import.import_file(feeds["card"], CARD_CSV, None)
    line = txn_by("EXAMPLE HOSTING")
    entry_id = bank_queue.post_line(line.id, {"account_id": chart["6300"]})["entry_id"]
    result = bank_queue.unpost(line.id)
    with db.SessionLocal() as session:
        assert session.get(JournalEntry, entry_id).reversed_by_entry_id == result["reversal_entry_id"]
        back = session.get(BankTxn, line.id)
        assert (back.status, back.entry_id) == ("NEW", None)
    bank_queue.post_line(line.id, {"account_id": chart["6110"]})  # re-post to the right account


def test_bank_entries_are_not_reversed_from_the_journal(chart, feeds):
    file_import.import_file(feeds["card"], CARD_CSV, None)
    entry_id = bank_queue.post_line(txn_by("EXAMPLE HOSTING").id, {"account_id": chart["6110"]})["entry_id"]
    with pytest.raises(JournalError, match="reversed from its own page"):
        with db.SessionLocal.begin() as session:
            journal.reverse_entry(session, entry_id)


def test_queue_listing_and_counts(chart, feeds):
    file_import.import_file(feeds["card"], CARD_CSV, None)
    bank_queue.post_line(txn_by("EXAMPLE HOSTING").id, {"account_id": chart["6110"]})
    review = bank_queue.list_lines("review")
    assert review["counts"] == {"review": 5, "excluded": 0, "posted": 1}
    assert review["lines"][0]["posted_date"] == "2026-09-27"
    posted = bank_queue.list_lines("posted")["lines"][0]
    assert posted["posted_to"] == ["6110 Hosting"]


# ------------------------------------------------------------------ API

def test_api_import_and_post(signed_in, chart, feeds):
    body = {"bank_account_id": feeds["card"], "content": CARD_CSV, "filename": "card.csv"}
    preview = signed_in.post("/api/banking/import/preview", json=body).get_json()
    assert preview["success"] and preview["preview"]["new"] == 6
    assert signed_in.post("/api/banking/import", json=body).get_json()["result"]["new"] == 6
    lines = signed_in.get("/api/banking/lines?view=review").get_json()["lines"]
    hosting = next(l for l in lines if l["description"] == "EXAMPLE HOSTING")
    assert hosting["amount"] == "-49.00"
    resp = signed_in.post(f"/api/banking/lines/{hosting['id']}/post", json={"account_id": chart["6110"]})
    assert resp.status_code == 200, resp.get_json()
    for path in ("/banking", "/banking/review", "/banking/import", "/banking/connections"):
        assert signed_in.get(path, follow_redirects=True).status_code == 200, path

""" EOF - test_bank.py """
