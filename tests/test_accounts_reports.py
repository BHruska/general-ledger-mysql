"""
General Ledger v0.2.0
File: tests/test_accounts_reports.py
Description: Chart-of-accounts rules (docs/DESIGN.md section 3.3), the trial balance
             with computed retained earnings (section 3.4), and the account register.
"""

from datetime import date
from decimal import Decimal

import pytest

import db
from utils import accounts, journal, reports
from utils.errors import LedgerError
from utils.journal import LineInput

D = Decimal


def post(entry_date, *pairs):
    with db.SessionLocal.begin() as session:
        journal.post_entry(session, entry_date=entry_date,
                           lines=[LineInput(a, D(x)) for a, x in pairs])


# ------------------------------------------------------------------ accounts

def test_number_must_fit_type_range():
    with pytest.raises(LedgerError, match="numbered 5000-7999"):
        accounts.create_account({"number": "4100", "name": "Oops", "type": "EXPENSE"})
    created = accounts.create_account({"number": "6400", "name": "Supplies", "type": "EXPENSE"})
    assert created["postable"] is True


def test_duplicate_number_refused():
    with pytest.raises(LedgerError, match="already"):
        accounts.create_account({"number": "6300", "name": "Travel 2", "type": "EXPENSE"})


def test_parent_rules(chart):
    with pytest.raises(LedgerError, match="one level deep"):
        accounts.create_account({"number": "6111", "name": "Deep", "type": "EXPENSE",
                                 "parent_id": chart["6110"]})
    with pytest.raises(LedgerError, match="parent's type"):
        accounts.create_account({"number": "6121", "name": "Wrong", "type": "EXPENSE",
                                 "parent_id": chart["4000"]})
    post(date(2026, 3, 1), (chart["6300"], "5"), (chart["1010"], "-5"))
    with pytest.raises(LedgerError, match="has postings"):
        accounts.create_account({"number": "6310", "name": "Airfare", "type": "EXPENSE",
                                 "parent_id": chart["6300"]})


def test_account_with_postings_is_deactivated_not_deleted(chart):
    post(date(2026, 3, 1), (chart["6300"], "5"), (chart["1010"], "-5"))
    with pytest.raises(LedgerError, match="deactivate it instead"):
        accounts.delete_account(chart["6300"])
    assert accounts.update_account(chart["6300"], {"is_active": False})["is_active"] is False


def test_type_change_refused_once_posted(chart):
    post(date(2026, 3, 1), (chart["6300"], "5"), (chart["1010"], "-5"))
    with pytest.raises(LedgerError, match="cannot change"):
        accounts.update_account(chart["6300"], {"type": "ASSET", "number": "1300"})


def test_settings_accounts_are_protected(chart):
    with pytest.raises(LedgerError, match="must stay active"):
        accounts.update_account(chart["3900"], {"is_active": False})
    with pytest.raises(LedgerError, match="Settings"):
        accounts.delete_account(chart["1200"])


def test_unused_account_deletes(chart):
    accounts.delete_account(chart["6300"])
    assert "6300" not in {a["number"] for a in accounts.list_accounts()}


def test_header_is_not_postable(chart):
    listed = {a["number"]: a for a in accounts.list_accounts()}
    assert listed["6100"]["is_header"] and not listed["6100"]["postable"]
    assert listed["6110"]["postable"]


# ------------------------------------------------------------------ trial balance

def test_trial_balance_balances_and_rolls_up(chart):
    post(date(2026, 2, 1), (chart["1010"], "5000"), (chart["3000"], "-5000"))
    post(date(2026, 3, 1), (chart["6110"], "20"), (chart["6120"], "30"), (chart["2010"], "-50"))
    tb = reports.trial_balance(date(2026, 6, 30))
    assert tb["balanced"] and tb["total_debit"] == tb["total_credit"] == "5050.00"
    rows = {r["number"]: r for r in tb["rows"]}
    assert rows["6100"]["is_header"] and rows["6100"]["debit"] == "50.00"
    assert rows["2010"]["credit"] == "50.00"


def test_prior_year_income_folds_into_retained_earnings(chart):
    post(date(2025, 6, 1), (chart["1010"], "1000"), (chart["4000"], "-1000"))   # 2025 revenue
    post(date(2025, 7, 1), (chart["6300"], "200"), (chart["1010"], "-200"))     # 2025 expense
    post(date(2026, 2, 1), (chart["1010"], "300"), (chart["4000"], "-300"))     # 2026 revenue
    tb = reports.trial_balance(date(2026, 6, 30))
    rows = {r["number"]: r for r in tb["rows"]}
    assert rows["4000"]["credit"] == "300.00"            # this fiscal year only
    assert "6300" not in rows                            # all of it was last year
    assert rows["3900"]["credit"] == "800.00"            # 1000 - 200, computed not posted
    assert tb["prior_years_net_income"] == "800.00"
    assert tb["balanced"]


def test_fiscal_year_start_month(chart):
    assert reports.fiscal_year_start(date(2026, 3, 15), 7) == date(2025, 7, 1)
    assert reports.fiscal_year_start(date(2026, 7, 1), 7) == date(2026, 7, 1)


# ------------------------------------------------------------------ register

def test_register_running_balance_in_normal_direction(chart):
    post(date(2026, 1, 5), (chart["6120"], "40"), (chart["2010"], "-40"))
    post(date(2026, 2, 5), (chart["6120"], "10"), (chart["2010"], "-10"))
    post(date(2026, 2, 20), (chart["2010"], "25"), (chart["1010"], "-25"))     # card payment
    r = reports.account_register(chart["2010"], date(2026, 2, 1), date(2026, 2, 28))
    assert r["opening_balance"] == "40.00"               # a liability, shown positive
    assert [l["balance"] for l in r["lines"]] == ["50.00", "25.00"]
    assert r["lines"][1]["other_side"] == "1010 Checking"
    assert r["closing_balance"] == "25.00"


def test_pnl_register_opening_restarts_each_fiscal_year(chart):
    post(date(2025, 12, 1), (chart["6300"], "100"), (chart["1010"], "-100"))
    post(date(2026, 1, 10), (chart["6300"], "5"), (chart["1010"], "-5"))
    r = reports.account_register(chart["6300"], date(2026, 2, 1), date(2026, 2, 28))
    assert r["opening_balance"] == "5.00"


def test_api_pages_render(signed_in):
    for path in ("/journal", "/journal/new", "/journal/registers", "/setup/accounts",
                 "/setup/settings", "/reports/trial-balance", "/banking", "/invoices"):
        assert signed_in.get(path).status_code == 200, path
    tb = signed_in.get("/api/reports/trial-balance?as_of=2026-06-30").get_json()
    assert tb["success"] and tb["report"]["balanced"]

""" EOF - test_accounts_reports.py """
