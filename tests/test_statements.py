"""
General Ledger v0.6.0
File: tests/test_statements.py
Description: Profit & Loss, Balance Sheet and General Ledger detail (utils/statements.py):
             QuickBooks-style sections, comparisons, computed net income and retained
             earnings, and GL opening balances.
"""

from datetime import date
from decimal import Decimal

import pytest

import db
from models import Account
from utils import journal, statements
from utils.errors import LedgerError
from utils.journal import LineInput


@pytest.fixture
def books(chart):
    ids = dict(chart)
    with db.SessionLocal.begin() as session:
        for number, name, type_ in (("5000", "Cost of Goods Sold", "EXPENSE"), ("4900", "Interest Income", "INCOME"),
                                    ("7000", "Loan Interest", "EXPENSE"), ("2500", "Auto Loan", "LIABILITY")):
            a = Account(number=number, name=name, type=type_)
            session.add(a)
            session.flush()
            ids[number] = a.id

    def post(when, *pairs):
        with db.SessionLocal.begin() as session:
            journal.post_entry(session, entry_date=when, lines=[LineInput(ids[n], Decimal(x)) for n, x in pairs])

    post(date(2025, 3, 1), ("1010", "10000"), ("3000", "-10000"))           # owner puts money in
    post(date(2025, 6, 1), ("1010", "2000"), ("4000", "-2000"))             # 2025 revenue
    post(date(2025, 7, 1), ("6300", "500"), ("1010", "-500"))               # 2025 travel
    post(date(2026, 2, 1), ("1010", "3000"), ("4000", "-3000"))             # 2026 revenue
    post(date(2026, 2, 5), ("5000", "400"), ("2010", "-400"))               # cost of sales, on the card
    post(date(2026, 3, 1), ("6110", "100"), ("6120", "50"), ("2010", "-150"))
    post(date(2026, 3, 9), ("1010", "20"), ("4900", "-20"))                 # interest earned
    post(date(2026, 4, 1), ("7000", "70"), ("1010", "-70"))                 # loan interest
    post(date(2026, 4, 2), ("1010", "5000"), ("2500", "-5000"))             # loan proceeds
    return ids


def section(report, key):
    return next(s for s in report["sections"] if s["key"] == key)


def test_pnl_sections_and_totals(books):
    r = statements.profit_and_loss(date(2026, 1, 1), date(2026, 6, 30))
    assert section(r, "income")["total"] == ["3000.00"]
    assert section(r, "cogs")["total"] == ["400.00"]
    assert r["gross_profit"] == ["2600.00"]
    expenses = section(r, "expenses")
    assert expenses["total"] == ["150.00"]
    # The Software header rolls up its two sub-accounts and is listed above them.
    rows = [(x["number"], x["is_header"], x["amounts"]) for x in expenses["rows"]]
    assert rows == [("6100", True, ["150.00"]), ("6110", False, ["100.00"]), ("6120", False, ["50.00"])]
    assert r["net_operating_income"] == ["2450.00"]
    assert (section(r, "other_income")["total"], section(r, "other_expense")["total"]) == (["20.00"], ["70.00"])
    assert r["net_other_income"] == ["-50.00"] and r["net_income"] == ["2400.00"]


def test_pnl_comparisons(books):
    r = statements.profit_and_loss(date(2026, 1, 1), date(2026, 12, 31), "prior_year")
    assert [c["start"] for c in r["columns"]] == ["2026-01-01", "2025-01-01"]
    assert section(r, "income")["total"] == ["3000.00", "2000.00"] and r["net_income"][1] == "1500.00"
    p = statements.profit_and_loss(date(2026, 3, 1), date(2026, 3, 31), "prior_period")
    assert p["columns"][1] == {"start": "2026-01-29", "end": "2026-02-28"}
    with pytest.raises(LedgerError):
        statements.profit_and_loss(date(2026, 3, 1), date(2026, 2, 1))


def test_balance_sheet_balances_with_computed_equity(books):
    r = statements.balance_sheet(date(2026, 6, 30), "prior_year")
    assert r["balanced"] == [True, True]
    # At 2025-06-30 the travel expense (07-01) had not happened yet.
    assert section(r, "bank")["total"] == ["19450.00", "12000.00"]
    assert section(r, "credit_cards")["total"] == ["550.00", "0.00"]
    assert section(r, "long_term_liabilities")["total"] == ["5000.00", "0.00"]
    # 2025's 1,500 profit is retained earnings (computed); 2026 so far is Net Income.
    equity = {x["number"]: x["amounts"] for x in section(r, "equity")["rows"]}
    assert equity["3900"] == ["1500.00", "0.00"] and equity["3000"] == ["10000.00", "10000.00"]
    assert r["net_income"] == ["2400.00", "2000.00"]
    assert r["total_assets"] == r["total_liabilities_and_equity"] == ["19450.00", "12000.00"]


def test_gl_detail_opening_split_and_filter(books):
    r = statements.gl_detail(date(2026, 3, 1), date(2026, 3, 31))
    by = {a["number"]: a for a in r["accounts"]}
    card = by["2010"]
    assert (card["opening"], card["closing"]) == ("400.00", "550.00")
    assert card["lines"][0]["split"] == "-Split-"          # 6110 and 6120 on the other side
    assert by["6110"]["lines"][0]["split"] == "-Split-"    # 6120 and the card, as QuickBooks shows it
    feb = {a["number"]: a for a in statements.gl_detail(date(2026, 2, 1), date(2026, 2, 28))["accounts"]}
    assert feb["5000"]["lines"][0]["split"] == "2010 Card"
    # A P&L account's opening counts only its fiscal year; 2025 revenue is not in it.
    assert by["4900"]["opening"] == "0.00"
    one = statements.gl_detail(date(2026, 1, 1), date(2026, 12, 31), books["4000"])
    assert [a["number"] for a in one["accounts"]] == ["4000"] and one["accounts"][0]["closing"] == "3000.00"


def test_pages_and_csv(signed_in, books):
    for path in ("/reports/profit-and-loss", "/reports/balance-sheet", "/reports/gl-detail", "/reports"):
        assert signed_in.get(path, follow_redirects=True).status_code == 200, path
    for path in ("/api/reports/profit-and-loss.csv?start=2026-01-01&end=2026-06-30&compare=prior_year",
                 "/api/reports/balance-sheet.csv?as_of=2026-06-30",
                 "/api/reports/gl-detail.csv?start=2026-01-01&end=2026-06-30"):
        resp = signed_in.get(path)
        assert resp.status_code == 200 and resp.mimetype == "text/csv", path
    text = signed_in.get("/api/reports/profit-and-loss.csv?start=2026-01-01&end=2026-06-30").get_data(as_text=True)
    assert "Net Income,,2400.00" in text
    bs = signed_in.get("/api/reports/balance-sheet?as_of=2026-06-30").get_json()["report"]
    assert bs["balanced"] == [True]

""" EOF - test_statements.py """
