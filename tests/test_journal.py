"""
General Ledger v0.2.0
File: tests/test_journal.py
Description: The accounting core (docs/DESIGN.md section 3): every post_entry() rule,
             reversal, edit-as-reverse-and-repost, the lock date, memo edits, the
             database triggers that back them up, and the global zero-sum invariant.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text

import db
from models import AuditLog, JournalEntry
from utils import journal, settings_manager
from utils.errors import LedgerError
from utils.journal import JournalError, LineInput
from utils.money import parse_amount

D = Decimal


def post(chart, entry_date=date(2026, 3, 1), lines=None, **kwargs):
    lines = lines or [LineInput(chart["6120"], D("49.00")), LineInput(chart["2010"], D("-49.00"))]
    with db.SessionLocal.begin() as session:
        entry = journal.post_entry(session, entry_date=entry_date, lines=lines, **kwargs)
        return entry.id


def refused(chart, lines, entry_date=date(2026, 3, 1), **kwargs) -> str:
    with pytest.raises(JournalError) as exc:
        post(chart, entry_date=entry_date, lines=lines, **kwargs)
    return str(exc.value)


def journal_total() -> Decimal:
    with db.SessionLocal() as session:
        return journal.journal_total(session)


def line_count() -> int:
    with db.engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM journal_line")).scalar()


@pytest.fixture(autouse=True)
def books_always_balance():
    """DESIGN.md 3.1: after every test, through every path, the journal sums to zero."""
    yield
    assert journal_total() == 0


# ------------------------------------------------------------------ post_entry rules

def test_balanced_entry_posts(chart):
    entry_id = post(chart, memo="GitHub")
    with db.SessionLocal() as session:
        entry = session.get(JournalEntry, entry_id)
        assert entry.source == "MANUAL"
        assert [(l.line_no, l.amount) for l in entry.lines] == [(1, D("49.00")), (2, D("-49.00"))]


def test_split_entry_posts(chart):
    post(chart, lines=[
        LineInput(chart["6120"], D("30.00")),
        LineInput(chart["6300"], D("19.00")),
        LineInput(chart["2010"], D("-49.00")),
    ])
    assert line_count() == 3


def test_fewer_than_two_lines_refused(chart):
    assert "at least two lines" in refused(chart, [LineInput(chart["6120"], D("0.00"))])
    assert line_count() == 0


def test_unbalanced_refused(chart):
    message = refused(chart, [LineInput(chart["6120"], D("49.00")), LineInput(chart["2010"], D("-48.99"))])
    assert "Out of balance by 0.01" in message
    assert line_count() == 0


def test_zero_line_refused(chart):
    message = refused(chart, [
        LineInput(chart["6120"], D("49.00")), LineInput(chart["6300"], D("0.00")),
        LineInput(chart["2010"], D("-49.00")),
    ])
    assert "cannot be 0.00" in message


def test_inactive_account_refused(chart):
    with db.engine.begin() as conn:
        conn.execute(text("UPDATE account SET is_active = FALSE WHERE id = :id"), {"id": chart["6300"]})
    assert "inactive" in refused(chart, [LineInput(chart["6300"], D("5")), LineInput(chart["2010"], D("-5"))])


def test_header_account_refused(chart):
    message = refused(chart, [LineInput(chart["6100"], D("5")), LineInput(chart["2010"], D("-5"))])
    assert "header account" in message


def test_unknown_account_refused(chart):
    assert "does not exist" in refused(chart, [LineInput(99999, D("5")), LineInput(chart["2010"], D("-5"))])


def test_bank_source_needs_a_bank_line(chart):
    assert "linked to its bank line" in refused(
        chart, [LineInput(chart["6120"], D("5")), LineInput(chart["1010"], D("-5"))], source="BANK")


def test_all_problems_reported_at_once(chart):
    with pytest.raises(JournalError) as exc:
        post(chart, lines=[LineInput(chart["6100"], D("5")), LineInput(chart["2010"], D("-4"))])
    assert len(exc.value.problems) == 2


def test_lock_date_refuses_on_and_before(chart):
    settings_manager.set_lock_date({"lock_date": "2026-01-31"})
    lines = [LineInput(chart["6120"], D("5")), LineInput(chart["2010"], D("-5"))]
    assert "lock date" in refused(chart, lines, entry_date=date(2026, 1, 31))
    assert "lock date" in refused(chart, lines, entry_date=date(2025, 12, 1))
    post(chart, entry_date=date(2026, 2, 1), lines=lines)


# ------------------------------------------------------------------ amount parsing

@pytest.mark.parametrize("raw, expected", [("49", "49.00"), ("1,234.50", "1234.50"), ("$10.1", "10.10")])
def test_amount_parsing(raw, expected):
    assert parse_amount(raw) == D(expected)


@pytest.mark.parametrize("raw", ["10.005", 10.5, True, "abc", "", "NaN", "Infinity"])
def test_amount_refusals(raw):
    with pytest.raises(LedgerError):
        parse_amount(raw)


def test_parse_lines_rules(chart):
    lines, problems = journal.parse_lines([
        {"account_id": chart["6120"], "debit": "10", "credit": ""},
        {"account_id": "", "debit": "", "credit": ""},                  # blank grid row, skipped
        {"account_id": chart["2010"], "debit": "5", "credit": "5"},
        {"account_id": chart["2010"], "debit": "-5"},
        {"account_id": None, "debit": "5"},
    ])
    assert [(l.account_id, l.amount) for l in lines] == [(chart["6120"], D("10.00"))]
    assert problems == [
        "Line 3 has both a debit and a credit; use one or the other.",
        "Line 4 is negative; enter it in the other column instead.",
        "Line 5 has no account.",
    ]


# ------------------------------------------------------------------ reversal and edit

def test_reversal_negates_and_links(chart):
    original = post(chart)
    with db.SessionLocal.begin() as session:
        reversal = journal.reverse_entry(session, original)
        reversal_id = reversal.id
        assert reversal.source == "REVERSAL"
        assert reversal.reverses_entry_id == original
        assert reversal.entry_date == date(2026, 3, 1)
        assert [l.amount for l in reversal.lines] == [D("-49.00"), D("49.00")]
    with db.SessionLocal() as session:
        assert session.get(JournalEntry, original).reversed_by_entry_id == reversal_id


def test_cannot_reverse_twice_or_reverse_a_reversal(chart):
    original = post(chart)
    with db.SessionLocal.begin() as session:
        reversal_id = journal.reverse_entry(session, original).id
    for target, words in ((original, "already reversed"), (reversal_id, "itself a reversal")):
        with pytest.raises(JournalError, match=words):
            with db.SessionLocal.begin() as session:
                journal.reverse_entry(session, target)


def test_reversal_not_before_original(chart):
    original = post(chart)
    with pytest.raises(JournalError, match="before the entry it reverses"):
        with db.SessionLocal.begin() as session:
            journal.reverse_entry(session, original, reversal_date=date(2026, 2, 28))


def test_locked_entry_cannot_be_reversed(chart):
    original = post(chart, entry_date=date(2026, 1, 15))
    settings_manager.set_lock_date({"lock_date": "2026-01-31"})
    with pytest.raises(JournalError, match="lock date"):
        with db.SessionLocal.begin() as session:
            journal.reverse_entry(session, original, reversal_date=date(2026, 2, 5))


def test_edit_reverses_and_reposts(chart):
    original = post(chart, memo="wrong account")
    result = journal.replace_manual(original, {
        "entry_date": "2026-03-01", "memo": "right account",
        "lines": [{"account_id": chart["6110"], "debit": "49.00"},
                  {"account_id": chart["2010"], "credit": "49.00"}],
    })
    assert result["reversal"]["reverses_entry_id"] == original
    assert result["entry"]["memo"] == "right account"
    assert journal.get_entry(original)["reversed_by_entry_id"] == result["reversal"]["id"]


def test_failed_edit_leaves_original_untouched(chart):
    original = post(chart)
    with pytest.raises(JournalError, match="Out of balance"):
        journal.replace_manual(original, {
            "entry_date": "2026-03-01",
            "lines": [{"account_id": chart["6110"], "debit": "49.00"},
                      {"account_id": chart["2010"], "credit": "48.00"}],
        })
    assert journal.get_entry(original)["reversed_by_entry_id"] is None
    assert line_count() == 2


def test_memo_edit_is_audited(chart):
    entry_id = post(chart, memo="before")
    journal.set_memo(entry_id, "after")
    with db.SessionLocal() as session:
        row = session.scalars(select(AuditLog)).one()
    assert (row.action, row.object_id, row.detail) == ("entry.memo", entry_id, {"old": "before", "new": "after"})


# ------------------------------------------------------------------ lock date

def test_lock_date_backwards_needs_reason_and_is_audited(chart):
    settings_manager.set_lock_date({"lock_date": "2026-06-30"})
    with pytest.raises(LedgerError, match="give a reason"):
        settings_manager.set_lock_date({"lock_date": "2026-03-31"})
    settings_manager.set_lock_date({"lock_date": "2026-03-31", "reason": "late vendor invoice"})
    with db.SessionLocal() as session:
        moves = session.scalars(select(AuditLog).where(AuditLog.action == "lock_date.move")
                                .order_by(AuditLog.id)).all()
    assert [m.detail["backwards"] for m in moves] == [False, True]
    assert moves[1].detail["reason"] == "late vendor invoice"


def test_lock_date_not_in_future(chart):
    with pytest.raises(LedgerError, match="future"):
        settings_manager.set_lock_date({"lock_date": "2999-01-01"})


# ------------------------------------------------------------------ the database backstop

@pytest.mark.parametrize("change", ["amount = amount + 1", f"account_id = account_id + 1", "line_no = 5"])
def test_trigger_refuses_posted_line_changes(chart, change):
    post(chart)
    with pytest.raises(Exception, match="immutable"):
        with db.engine.begin() as conn:
            conn.execute(text(f"UPDATE journal_line SET {change} WHERE line_no = 1"))


def test_trigger_allows_line_memo_and_clearing(chart):
    post(chart)
    with db.engine.begin() as conn:
        conn.execute(text("UPDATE journal_line SET memo = 'receipt', cleared_recon_id = 7 WHERE line_no = 1"))


def test_trigger_refuses_delete(chart):
    post(chart)
    for sql in ("DELETE FROM journal_line", "DELETE FROM journal_entry"):
        with pytest.raises(Exception, match="never deleted"):
            with db.engine.begin() as conn:
                conn.execute(text(sql))


def test_trigger_refuses_zero_and_locked_inserts(chart):
    entry_id = post(chart, entry_date=date(2026, 1, 10))
    with pytest.raises(Exception, match="cannot be 0.00"):
        with db.engine.begin() as conn:
            conn.execute(text("INSERT INTO journal_line (entry_id, line_no, account_id, amount) "
                              "VALUES (:e, 9, :a, 0)"), {"e": entry_id, "a": chart["6300"]})
    settings_manager.set_lock_date({"lock_date": "2026-01-31"})
    with pytest.raises(Exception, match="lock date"):
        with db.engine.begin() as conn:
            conn.execute(text("INSERT INTO journal_line (entry_id, line_no, account_id, amount) "
                              "VALUES (:e, 9, :a, 1)"), {"e": entry_id, "a": chart["6300"]})


def test_trigger_refuses_entry_date_change(chart):
    post(chart)
    with pytest.raises(Exception, match="immutable"):
        with db.engine.begin() as conn:
            conn.execute(text("UPDATE journal_entry SET entry_date = '2025-01-01'"))
    with db.engine.begin() as conn:
        conn.execute(text("UPDATE journal_entry SET memo = 'fine'"))


# ------------------------------------------------------------------ the API

def test_api_validate_reports_totals_and_problems(signed_in, chart):
    check = signed_in.post("/api/journal/validate", json={
        "entry_date": "2026-03-01",
        "lines": [{"account_id": chart["6120"], "debit": "10.00"},
                  {"account_id": chart["2010"], "credit": "7.50"}],
    }).get_json()["check"]
    assert check == {"ok": False, "problems": ["Out of balance by 2.50 (debits are higher)."],
                     "total_debits": "10.00", "total_credits": "7.50", "difference": "2.50"}


def test_api_post_list_reverse(signed_in, chart):
    resp = signed_in.post("/api/journal/entries", json={
        "entry_date": "2026-03-01", "memo": "Hosting",
        "lines": [{"account_id": chart["6110"], "debit": "20"},
                  {"account_id": chart["1010"], "credit": "20"}],
    })
    assert resp.status_code == 200, resp.get_json()
    entry_id = resp.get_json()["entry"]["id"]

    listed = signed_in.get("/api/journal/entries?start=2026-01-01&end=2026-12-31").get_json()
    assert [e["id"] for e in listed["entries"]] == [entry_id]
    assert listed["entries"][0]["lines"][0]["debit"] == "20.00"

    rev = signed_in.post(f"/api/journal/entries/{entry_id}/reverse", json={})
    assert rev.status_code == 200
    again = signed_in.post(f"/api/journal/entries/{entry_id}/reverse", json={})
    assert again.status_code == 400
    assert "already reversed" in again.get_json()["error"]


def test_api_refusal_lists_problems(signed_in, chart):
    resp = signed_in.post("/api/journal/entries", json={
        "entry_date": "2026-03-01",
        "lines": [{"account_id": chart["6100"], "debit": "20"},
                  {"account_id": chart["1010"], "credit": "19"}],
    })
    assert resp.status_code == 400
    assert len(resp.get_json()["problems"]) == 2


def test_api_money_never_accepts_json_numbers(signed_in, chart):
    resp = signed_in.post("/api/journal/entries", json={
        "entry_date": "2026-03-01",
        "lines": [{"account_id": chart["6110"], "debit": 0.1},
                  {"account_id": chart["1010"], "credit": "0.10"}],
    })
    assert resp.status_code == 400
    assert "string" in resp.get_json()["error"]


def test_api_missing_entry_is_404(signed_in):
    assert signed_in.get("/api/journal/entries/424242").status_code == 404

""" EOF - test_journal.py """
