"""
General Ledger v0.3.3
File: tests/test_payees.py
Description: The QuickBooks payee import (last used, archive by date, defaults from
             consistent history) and payee management, against synthetic exports in
             QBO's real layouts and the conftest TEST_CHART.
"""

from datetime import date

import pytest
from sqlalchemy import select

import db
from models import Payee
from utils import payees
from utils.errors import LedgerError
from utils.migration import qbo_payees

VENDORS = '''"Example Co, LLC",,,,,,,,
Vendor Contact List,,,,,,,,

Vendor,Company,Phone numbers,Email,Full name,Billing address,Account #,Tax ID,Track 1099
Acme Hosting,,,,,"1 Main St
Springfield",,,No
Travel Co,,,,,,,,No
Never Used Vendor,,,,,,,,Yes
amazon,,,,,,,,No



" Wednesday, September 30, 2026 11:11 AM GMT-05:00",,,,,,,,
'''

TXNS = '''"Example Co, LLC",,,,,,,,
Transaction Detail by Account,,,,,,,,
All Dates,,,,,,,,

,Transaction date,Transaction type,Num,Name,Description,Split,Amount,Balance
Card,,,,,,,,
,01/05/2026,Expense,,Acme Hosting,ACME,Software:Hosting,20.00,20.00
,02/05/2026,Expense,,Acme Hosting,ACME,Software:Hosting,20.00,40.00
,03/05/2026,Expense,,Acme Hosting,ACME,Software:Hosting,20.00,60.00
,04/05/2026,Expense,,Acme Hosting,ACME,Travel,20.00,80.00
,05/01/2019,Expense,,Travel Co,FLIGHT,Travel,300.00,380.00
,06/01/2025,Expense,,AMAZON,AMZN,Software:SaaS,10.00,390.00
,07/01/2025,Expense,,Amazon,AMZN,Travel,10.00,400.00
,08/01/2025,Credit Card Payment,,Card Payment,AUTOPAY,Checking,-400.00,0.00
Total for Card,,,,,,,$0.00,
Checking,,,,,,,,
,03/10/2026,Deposit,,Big Client,DEPOSIT,Revenue,1500.00,1500.00
Total for Checking,,,,,,,"$1,500.00",
Accounts Receivable,,,,,,,,
,03/01/2026,Invoice,1001,Big Client,,Revenue,1500.00,1500.00
Total for Accounts Receivable,,,,,,,"$1,500.00",
TOTAL,,,,,,,"$1,500.00",



"Accrual Basis Wednesday, September 30, 2026 11:46 AM GMT-05:00",,,,,,,,
'''


def planned(active_since=date(2024, 1, 1)):
    rows, summary = qbo_payees.plan(VENDORS, TXNS, active_since)
    return {p.name: p for p in rows}, summary


def test_every_name_comes_across_case_insensitively(chart):
    rows, s = planned()
    # "amazon" (vendor list), "AMAZON" and "Amazon" (history) are one payee.
    assert set(rows) == {"Acme Hosting", "Travel Co", "Never Used Vendor", "amazon", "Card Payment", "Big Client"}
    assert rows["amazon"].lines == 2 and rows["amazon"].last_used == date(2025, 7, 1)


def test_active_by_last_use(chart):
    rows, s = planned()
    assert rows["Acme Hosting"].is_active and rows["amazon"].is_active
    assert not rows["Travel Co"].is_active                 # last used 2019
    assert not rows["Never Used Vendor"].is_active and rows["Never Used Vendor"].last_used is None
    assert (s["active"], s["archived"], s["never_used"]) == (4, 2, 1)


def test_default_account_only_when_consistent(chart):
    rows, _ = planned()
    assert rows["Acme Hosting"].default_account_id == chart["6110"]    # 3 of 4 = 75%
    assert rows["Travel Co"].default_account_id == chart["6300"]
    assert rows["amazon"].default_account_id is None                   # 50/50
    assert rows["Card Payment"].default_account_id is None             # a transfer, not a default
    assert rows["Big Client"].is_customer and not rows["Big Client"].is_vendor


def test_recent_history_decides_the_default(chart):
    old_habit = "".join(f",0{m}/01/2019,Expense,,Old Habit,X,Travel,5.00,0\n" for m in (1, 2, 3))
    txns = TXNS.replace("Total for Card", old_habit + ",03/01/2025,Expense,,Old Habit,X,Software:SaaS,5.00,0\nTotal for Card")
    rows, _ = qbo_payees.plan(VENDORS, txns, date(2024, 1, 1))
    habit = {p.name: p for p in rows}["Old Habit"]
    assert habit.default_account_id == chart["6120"]   # 3 old lines to Travel lose to 1 recent
    assert habit.is_vendor                             # an Expense line makes a vendor


def test_header_without_general_gets_no_default(chart):
    txns = TXNS.replace("Software:Hosting,20.00", "Software,20.00")
    rows, _ = qbo_payees.plan(VENDORS, txns, date(2024, 1, 1))
    assert {p.name: p for p in rows}["Acme Hosting"].default_account_id is None


def test_apply_and_refuse_second_run(chart):
    s = qbo_payees.apply(VENDORS, TXNS, date(2024, 1, 1))
    assert s["payees"] == 6
    with db.SessionLocal() as session:
        acme = session.scalar(select(Payee).where(Payee.name == "Acme Hosting"))
        assert acme.address == "1 Main St\nSpringfield" and acme.last_used_on == date(2026, 4, 5)
        assert session.scalar(select(Payee).where(Payee.name == "Never Used Vendor")).is_1099_vendor
    with pytest.raises(LedgerError, match="already exist"):
        qbo_payees.apply(VENDORS, TXNS, date(2024, 1, 1))
    assert qbo_payees.apply(VENDORS, TXNS, date(2026, 1, 1), replace=True)["active"] == 2


def test_archive_unused_and_reactivate(chart):
    qbo_payees.apply(VENDORS, TXNS, date(2000, 1, 1))
    assert payees.list_payees("active")["counts"] == {"active": 5, "archived": 1}
    assert payees.archive_unused({"before": "2026-01-01"})["archived"] == 3   # amazon, Travel Co, Card Payment
    listed = {p["name"]: p for p in payees.list_payees("all")["payees"]}
    assert not listed["amazon"]["is_active"] and listed["Acme Hosting"]["is_active"]
    payees.update_payee(listed["amazon"]["id"], {"is_active": True})
    assert payees.list_payees("active")["counts"]["active"] == 3


def test_update_rules(chart):
    qbo_payees.apply(VENDORS, TXNS, date(2024, 1, 1))
    acme = next(p for p in payees.list_payees("all")["payees"] if p["name"] == "Acme Hosting")
    with pytest.raises(LedgerError, match="header"):
        payees.update_payee(acme["id"], {"default_account_id": chart["6100"]})
    with pytest.raises(LedgerError, match="transfer"):
        payees.update_payee(acme["id"], {"default_account_id": chart["2010"]})
    with pytest.raises(LedgerError, match="already called"):
        payees.update_payee(acme["id"], {"name": "travel co"})
    assert payees.update_payee(acme["id"], {"default_account_id": chart["6120"]})["default_account"] == "6120 SaaS"


def test_payees_page_and_api(signed_in, chart):
    qbo_payees.apply(VENDORS, TXNS, date(2024, 1, 1))
    assert signed_in.get("/setup/payees").status_code == 200
    data = signed_in.get("/api/payees?view=archived").get_json()
    assert data["success"] and {p["name"] for p in data["payees"]} == {"Travel Co", "Never Used Vendor"}
    # All four active payees were last used before June 2026.
    assert signed_in.post("/api/payees/archive-unused", json={"before": "2026-06-01"}).get_json()["archived"] == 4

""" EOF - test_payees.py """
