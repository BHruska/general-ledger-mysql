"""
General Ledger v0.6.0
File: tests/test_qbo_history.py
Description: QuickBooks history as journal entries (utils/migration/qbo_journal.py) and the
             boundary rule for invoice history (qbo_invoices --before), on synthetic
             exports in QBO's real layouts, quirks included.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

import db
from models import Account, Invoice, JournalEntry, Settings
from utils import journal, reports
from utils.errors import LedgerError
from utils.journal import LineInput
from utils.migration import qbo_invoices, qbo_journal

JOURNAL = '''"Example Co, LLC",,,,,,,,
Journal,,,,,,,,
All Dates,,,,,,,,

,Transaction date,Transaction type,Num,Name,Description,Account Name,Debit,Credit
25,,,,,,,,
,12/31/2024,Deposit,,,Opening deposit,Old Checking (deleted),"1,000.00",
,12/31/2024,Deposit,,,,Owner's Equity,,"1,000.00"
Total for 25,,,,,,,"$1,000.00","$1,000.00"
26,,,,,,,,
,03/05/2025,Expense,,Acme Hosting,HOSTING,Software:Hosting,49.00,
,03/05/2025,Expense,,Acme Hosting,,Card,,49.00
,03/05/2025,Expense,,Acme Hosting,,,,
Total for 26,,,,,,,$49.00,$49.00
27,,,,,,,,
,04/01/2025,Invoice,5001,Acme Corp,,Accounts Receivable,500.00,
,04/01/2025,Invoice,5001,Acme Corp,Web Site Hosting,Revenue,,500.00
Total for 27,,,,,,,$500.00,$500.00
28,,,,,,,,
,05/01/2025,Payment,,Acme Corp,,,,
,05/01/2025,Payment,,Acme Corp,,Accounts Receivable,,
Total for 28,,,,,,,,
29,,,,,,,,
,06/15/2025,Expense,,Parent Posting,DIRECT,Software,10.00,
,06/15/2025,Expense,,Parent Posting,,Card,,10.00
Total for 29,,,,,,,$10.00,$10.00
30,,,,,,,,
,07/10/2026,Expense,,Late,AFTER BOUNDARY,Travel,20.00,
,07/10/2026,Expense,,Late,,Card,,20.00
Total for 30,,,,,,,$20.00,$20.00
TOTAL,,,,,,,"$1,579.00","$1,579.00"



" Wednesday, September 30, 2026 02:43 PM GMT-05:00",,,,,,,,
'''
BEFORE = date(2026, 7, 1)


@pytest.fixture
def with_general(chart):
    """TEST_CHART plus the "- General" sub-account qbo_chart.py gives every parent."""
    with db.SessionLocal.begin() as session:
        session.add(Account(number="6101", name="Software - General", type="EXPENSE", parent_id=chart["6100"]))
    return chart


def test_parse_skips_zero_lines_and_all_zero_transactions():
    txns = qbo_journal.parse(JOURNAL)
    by_id = {t.qbo_id: t for t in txns}
    assert len(by_id["26"].lines) == 2        # the blank-account zero line is dropped
    assert by_id["28"].lines == []            # QBO's empty "payment"
    assert by_id["27"].lines[0].amount == Decimal("500.00") and by_id["27"].lines[1].amount == Decimal("-500.00")


def test_unbalanced_transaction_refused():
    with pytest.raises(LedgerError, match="does not balance"):
        qbo_journal.parse(JOURNAL.replace(",03/05/2025,Expense,,Acme Hosting,,Card,,49.00",
                                          ",03/05/2025,Expense,,Acme Hosting,,Card,,48.00"))


def test_amount_with_more_than_two_places_refused_not_rounded():
    with pytest.raises(LedgerError, match="more than two decimal places"):
        qbo_journal.parse(JOURNAL.replace("Software:Hosting,49.00,", "Software:Hosting,49.004,"))


def test_preview_resolves_accounts_and_honours_the_boundary(with_general):
    s = qbo_journal.preview(JOURNAL, BEFORE)
    assert (s["transactions"], s["lines"], s["skipped_on_or_after_boundary"], s["skipped_all_zero"]) == (4, 8, 1, 1)
    assert s["deleted_accounts_to_create"] == {"Old Checking (deleted)": 1}
    assert s["unknown_accounts"] == {}


def test_apply_imports_locks_and_links(with_general):
    s = qbo_journal.apply(JOURNAL, BEFORE)
    assert (s["transactions"], s["lock_date"]) == (4, "2026-06-30")
    with db.SessionLocal() as session:
        closed = session.scalar(select(Account).where(Account.name == "Old Checking (closed)"))
        assert closed.type == "ASSET" and not closed.is_active and closed.is_bank_account
        assert session.get(Settings, 1).lock_date == date(2026, 6, 30)
        sources = {e.source for e in session.scalars(select(JournalEntry))}
        assert sources == {"IMPORT"}
    # A posting to a QBO parent lands on its "- General" sub-account, never the header.
    # (At 2025 year end: by 2026-06-30 those expenses are folded into retained earnings.)
    tb = {r["number"]: r for r in reports.trial_balance(date(2025, 12, 31))["rows"]}
    assert tb["6101"]["debit"] == "10.00" and tb["6110"]["debit"] == "49.00"
    assert tb["6100"]["is_header"] and reports.trial_balance(date(2026, 6, 30))["balanced"]
    with pytest.raises(LedgerError, match="already imported"):
        qbo_journal.apply(JOURNAL, BEFORE)


def test_refuses_when_books_already_have_entries_before_the_boundary(with_general, chart):
    with db.SessionLocal.begin() as session:
        journal.post_entry(session, entry_date=date(2025, 1, 5), lines=[
            LineInput(chart["6300"], Decimal("5")), LineInput(chart["1010"], Decimal("-5"))])
    with pytest.raises(LedgerError, match="count them twice"):
        qbo_journal.apply(JOURNAL, BEFORE)


def test_unknown_account_refused(with_general):
    with pytest.raises(LedgerError, match="not in the chart"):
        qbo_journal.apply(JOURNAL.replace("Software:Hosting", "Software:Nonexistent"), BEFORE)


# ------------------------------------------------------------------ invoices at the boundary

SALES = '''"Example Co, LLC",,,,,,,,,
Sales by Product/Service Detail,,,,,,,,,
All Dates,,,,,,,,,

,Transaction date,Transaction type,Num,Customer full name,Description,Quantity,Sales price,Amount,Balance
Web,,,,,,,,,
,04/01/2026,Invoice,5001,Acme Corp,Hosting,1.00,500.00,500.00,500.00
,05/01/2026,Invoice,5002,Acme Corp,Hosting,1.00,300.00,300.00,800.00
,08/01/2026,Invoice,5003,Acme Corp,Hosting,1.00,100.00,100.00,900.00
TOTAL,,,,,,,,$900.00,
'''
PAYMENTS = '''"Example Co, LLC",,,,,
Invoices and Received Payments,,,,,
All Dates,,,,,

,Date,Transaction type,Memo/Description,Transaction number,Amount
Acme Corp,,,,,
,05/15/2026,Payment,,,500.00
,08/04/2026,Payment,,,300.00
'''
OPEN = ''',Date,Transaction type,Num,Term,Due date,Open balance
Acme Corp,,,,,,
,08/01/2026,Invoice,5003,Upon Receipt,08/01/2026,100.00
'''
CUSTOMERS = '''Customer full name,Phone numbers,Email,Full name,Bill address,Ship address
Acme Corp,,a@acme.example,,,
'''


def test_invoice_paid_after_the_boundary_is_open_at_it(chart):
    s = qbo_invoices.apply(SALES, PAYMENTS, OPEN, CUSTOMERS, active_since=date(2024, 1, 1),
                           income_account_number="4000", before=BEFORE)
    assert (s["invoices"], s["skipped_on_or_after_boundary"], s["open_total"]) == (2, 1, "300.00")
    with db.SessionLocal() as session:
        inv = {i.number: i for i in session.scalars(select(Invoice))}
    assert set(inv) == {"5001", "5002"}                      # 5003 was issued after the boundary
    assert (inv["5001"].status, inv["5001"].paid_on) == ("PAID", date(2026, 5, 15))
    # Paid on 08/04, after the boundary: open here, for the feed's deposit to pay.
    assert (inv["5002"].status, inv["5002"].balance, inv["5002"].payments) == ("OPEN", Decimal("300.00"), [])

""" EOF - test_qbo_history.py """
