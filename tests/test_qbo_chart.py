"""
General Ledger v0.3.1
File: tests/test_qbo_chart.py
Description: The QuickBooks Online chart import (utils/migration/qbo_chart.py), against a
             synthetic Account List in QBO's real export layout.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

import db
from models import Account, Settings
from utils import journal
from utils.errors import LedgerError
from utils.journal import LineInput
from utils.migration import qbo_chart

KIDS = "\n".join(f"Web Services:Kid {i},Expenses,Other Miscellaneous Service Cost,," for i in range(9))
ACCOUNT_LIST = f'''"Example Co, LLC",,,,
Account List,,,,

Account Name,Type,Detail type,Description,Total balance
Main Checking,Bank,Checking,Operating account,400.08
Accounts Receivable,Accounts receivable (A/R),Accounts Receivable (A/R),,975.00
Truck,Fixed Assets,Other fixed assets,,"49,167.00"
Truck:Accum. Depre.,Fixed Assets,Other fixed assets,,"-24,258.00"
Company Visa,Credit Card,Credit Card,,"25,032.09"
Owner Draws,Equity,Owner's Equity,,
Retained Earnings,Equity,Retained Earnings,,
Consulting Income,Income,Service/Fee Income,,
Advertising,Expenses,Advertising/Promotional,"Ads and cards",
Web Services,Expenses,Other Miscellaneous Service Cost,,
{KIDS}
Zoo Fees,Expenses,Other Miscellaneous Service Cost,,
Loan Interest,Other Expense,Other Miscellaneous Expense,,
TOTAL,,,,"$1.00"



" Wednesday, September 30, 2026 11:10 AM GMT-05:00",,,,
'''


def by_name(preview) -> dict:
    return {a["name"]: a for a in preview["accounts"]}


def test_parse_skips_title_total_and_footer():
    accounts = qbo_chart.parse(ACCOUNT_LIST)
    assert len(accounts) == 21
    kid = next(a for a in accounts if a.full_name == "Web Services:Kid 0")
    assert (kid.name, kid.parent) == ("Kid 0", "Web Services")


def test_numbering_types_and_general_subaccounts():
    p = qbo_chart.preview(ACCOUNT_LIST)
    a = by_name(p)
    assert (a["Main Checking"]["number"], a["Main Checking"]["type"], a["Main Checking"]["bank"]) == ("1010", "ASSET", True)
    assert a["Company Visa"]["number"] == "2100" and a["Company Visa"]["bank"]
    assert a["Retained Earnings"]["number"] == "3900"
    assert a["Owner Draws"]["number"] == "3000"
    assert a["Loan Interest"]["number"] == "7000" and a["Loan Interest"]["type"] == "EXPENSE"
    # A parent gets "- General" as +1, then its sub-accounts alphabetically.
    assert a["Web Services"]["number"] == "6010"
    assert a["Web Services - General"]["number"] == "6011" and a["Web Services - General"]["parent"] == "6010"
    assert a["Kid 8"]["number"] == "6020"
    # Ten sub-accounts overflow the ten-slot; the next account moves on to a clean multiple.
    assert a["Zoo Fees"]["number"] == "6030"
    assert p["general_subaccounts"] == 2


@pytest.mark.parametrize("bad, words", [
    ("Name,Amount\nx,1\n", "not a QuickBooks Online Account List"),
    (ACCOUNT_LIST.replace("Web Services:Kid 0,", "Web Services:Kid 0:Deep,"), "more than one level"),
    (ACCOUNT_LIST.replace("Zoo Fees,Expenses", "Zoo Fees,Mystery"), "does not map"),
])
def test_refusals(bad, words):
    with pytest.raises(LedgerError, match=words):
        qbo_chart.preview(bad)


def test_apply_replaces_chart_and_repoints_settings(chart):
    result = qbo_chart.apply(ACCOUNT_LIST)
    assert result == {"imported": 23, "replaced": len(chart)}
    with db.SessionLocal() as session:
        accounts = {a.number: a for a in session.scalars(select(Account))}
        settings = session.get(Settings, 1)
        assert settings.retained_earnings_account_id == accounts["3900"].id
        assert session.get(Account, settings.ar_account_id).name == "Accounts Receivable"
        assert accounts["6011"].parent_id == accounts["6010"].id
        assert all(not n.startswith("N") for n in accounts)
    # The new chart is usable: post to a General sub-account.
    with db.SessionLocal.begin() as session:
        journal.post_entry(session, entry_date=date(2026, 9, 1), lines=[
            LineInput(accounts["6011"].id, Decimal("20.93")), LineInput(accounts["2100"].id, Decimal("-20.93"))])


def test_apply_refuses_when_books_are_not_empty(chart):
    with db.SessionLocal.begin() as session:
        journal.post_entry(session, entry_date=date(2026, 9, 1), lines=[
            LineInput(chart["6300"], Decimal("5")), LineInput(chart["1010"], Decimal("-5"))])
    with pytest.raises(LedgerError, match="not empty"):
        qbo_chart.apply(ACCOUNT_LIST)
    with db.SessionLocal() as session:
        assert session.scalar(select(Account).where(Account.number == "6300")) is not None

""" EOF - test_qbo_chart.py """
