"""
General Ledger v0.5.0
File: tests/test_invoices.py
Description: Invoice history from QuickBooks (oldest-first payment matching, Open Invoices
             as the authority, customers), the invoice and customer APIs, and A/R aging.
             Synthetic exports in QBO's real layouts, oddities included.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

import db
from models import Invoice, InvoicePayment, Payee, Settings
from utils import invoices
from utils.errors import LedgerError
from utils.migration import qbo_invoices

SALES = '''"Example Co, LLC",,,,,,,,,
Sales by Product/Service Detail,,,,,,,,,
All Dates,,,,,,,,,

,Transaction date,Transaction type,Num,Customer full name,Description,Quantity,Sales price,Amount,Balance
Web,,,,,,,,,
,01/10/2025,Invoice,5001,Acme Corp,Web Site Hosting 2025,1.00,"1,000.00","1,000.00","1,000.00"
,02/10/2025,Invoice,5002,Acme Corp,Web Site Help - 1 Hr,1.00,100.00,100.00,"1,100.00"
,02/10/2025,Invoice,5002,Acme Corp,Domain renewal,,,25.00,"1,125.00"
,03/01/2025,Invoice,5003,Beta LLC,Web Site Maintenance,12.00,75.00,900.00,"2,025.00"
,04/01/2026,Invoice,5004,Acme Corp,Web Site Hosting 2026,1.00,"1,000.00","1,000.00","3,025.00"
,04/02/2026,Invoice,5005,Beta LLC,Web Site - Theme,0.00,,0.00,"3,025.00"
Total for Web,,,,,,,,"$3,025.00",
TOTAL,,,,,,,,"$3,025.00",



"Accrual Basis Wednesday, September 30, 2026 01:47 PM GMT-05:00",,,,,,,,,
'''

PAYMENTS = '''"Example Co, LLC",,,,,
Invoices and Received Payments,,,,,
All Dates,,,,,

,Date,Transaction type,Memo/Description,Transaction number,Amount
Acme Corp,,,,,
,01/10/2025,Invoice,,5001,"1,000.00"
,03/15/2025,Payment,,,"1,125.00"
,02/10/2025,Invoice,,5002,125.00
Beta LLC,,,,,
,03/01/2025,Invoice,,5003,900.00
,04/20/2025,Deposit,,1,-900.00
,04/21/2025,Payment,,,
,04/02/2026,Invoice,,5005,0.00



" Wednesday, September 30, 2026 01:49 PM GMT-05:00",,,,,
'''

OPEN = ''',Date,Transaction type,Num,Term,Due date,Open balance
Acme Corp,,,,,,
,04/01/2026,Invoice,5004,Upon Receipt,04/30/2026,"1,000.00"
Total for Acme Corp,,,,,,"$1,000.00"
TOTAL,,,,,,"$1,000.00"
'''

CUSTOMERS = '''"Example Co, LLC",,,,,
Customer Contact List,,,,,

Customer full name,Phone numbers,Email,Full name,Bill address,Ship address
Acme Corp,,billing@acme.example,Ann Acme,1 Main St Springfield IL,
SHELL OIL 123,,,,,



" Wednesday, September 30, 2026 01:46 PM GMT-05:00",,,,,
'''


def run(**kw):
    return qbo_invoices.apply(SALES, PAYMENTS, OPEN, CUSTOMERS, active_since=date(2024, 1, 1),
                              income_account_number="4000", **kw)


def inv(number) -> Invoice:
    with db.SessionLocal() as session:
        return session.scalar(select(Invoice).where(Invoice.number == number))


def test_preview_totals_open_and_numbering():
    s = qbo_invoices.preview(SALES, PAYMENTS, OPEN, CUSTOMERS)
    assert (s["invoices"], s["customers"], s["lines"], s["total_invoiced"]) == (5, 2, 6, "3025.00")
    assert s["open_total"] == "1000.00" and s["open"][0]["number"] == "5004"
    assert s["next_number"] == 5006
    # Beta's 5003 is paid per QuickBooks, but its only "payments" are a negative deposit
    # and a blank row: nothing to match, so it is reported rather than invented.
    assert s["paid_without_matching_payment"] == {"5003": "900.00"}


def test_apply_imports_history_without_posting(chart):
    s = run()
    assert s["invoices"] == 5
    a1, a2, a4 = inv("5001"), inv("5002"), inv("5004")
    # Acme's one payment of 1,125 paid 5001 then 5002, oldest first.
    assert (a1.status, a1.amount_paid, a1.paid_on) == ("PAID", Decimal("1000.00"), date(2025, 3, 15))
    assert (a2.total, a2.paid_on) == (Decimal("125.00"), date(2025, 3, 15))
    assert (a4.status, a4.balance, a4.due_date, a4.terms) == ("OPEN", Decimal("1000.00"), date(2026, 4, 30), "Upon Receipt")
    assert {i.source for i in (a1, a2, a4)} == {"QBO"} and a1.entry_id is None
    with db.SessionLocal() as session:
        assert {p.source for p in session.scalars(select(InvoicePayment))} == {"QBO_DERIVED"}
        assert all(p.entry_id is None for p in session.scalars(select(InvoicePayment)))
        acme = session.scalar(select(Payee).where(Payee.name == "Acme Corp"))
        assert acme.is_customer and acme.email == "billing@acme.example" and acme.last_used_on == date(2026, 4, 1)
        assert session.scalar(select(Payee).where(Payee.name == "SHELL OIL 123")) is None  # not an invoiced customer
        settings = session.get(Settings, 1)
        assert settings.next_invoice_seq == 5006 and settings.default_income_account_id == chart["4000"]


def test_blank_quantity_and_zero_invoice_lines(chart):
    run()
    detail = invoices.get_invoice(inv("5002").id)
    assert [(l["quantity"], l["rate"], l["amount"]) for l in detail["lines"]] == [
        ("1.00", "100.00", "100.00"), ("1.00", "25.00", "25.00")]
    zero = inv("5005")
    assert zero.total == 0 and zero.status == "PAID"


def test_existing_payee_is_reused_and_second_run_refused(chart):
    with db.SessionLocal.begin() as session:
        session.add(Payee(name="acme corp", is_vendor=True, is_customer=False, is_active=False))
    run()
    with db.SessionLocal() as session:
        acme = session.scalars(select(Payee).where(Payee.name == "acme corp")).all()
        assert len(acme) == 1 and acme[0].is_customer and acme[0].is_vendor and acme[0].is_active
    with pytest.raises(LedgerError, match="already exist"):
        run()
    assert run(replace=True)["invoices"] == 5


def test_open_invoice_missing_from_sales_is_refused():
    with pytest.raises(LedgerError, match="not in the Sales detail"):
        qbo_invoices.preview(SALES, PAYMENTS, OPEN.replace("5004", "5999"), CUSTOMERS)


def test_list_and_customers(chart):
    run()
    listed = invoices.list_invoices()
    assert listed["counts"]["OPEN"] == 1 and listed["open_total"] == "1000.00"
    assert [i["number"] for i in invoices.list_invoices(status="OPEN")["invoices"]] == ["5004"]
    customers = {c["name"]: c for c in invoices.list_customers()["customers"]}
    assert customers["Acme Corp"]["invoices"] == 3 and customers["Acme Corp"]["open_balance"] == "1000.00"


def test_ar_aging_at_dates(chart):
    run()
    # Before Acme's March payment both of its invoices were owed. History invoices are due
    # on their issue date, so 5001 was 59 days late and 5002 was 28.
    before = invoices.ar_aging(date(2025, 3, 10))
    acme = next(r for r in before["rows"] if r["customer"] == "Acme Corp")
    assert (acme["d31_60"], acme["d1_30"], acme["total"]) == ("1000.00", "125.00", "1125.00")
    # Beta's 5003 is paid with no matchable payment: never shown as owed.
    assert all(r["customer"] != "Beta LLC" for r in before["rows"])
    today = invoices.ar_aging(date(2026, 9, 30))
    assert today["totals"]["total"] == "1000.00" and today["totals"]["d90_plus"] == "1000.00"
    assert today["detail"][0]["days_past_due"] == 153


def test_pages_and_api(signed_in, chart):
    run()
    for path in ("/invoices", "/invoices/customers", f"/invoices/{inv('5004').id}", "/reports/ar-aging"):
        assert signed_in.get(path).status_code == 200, path
    assert signed_in.get("/api/invoices?status=OPEN").get_json()["invoices"][0]["number"] == "5004"
    detail = signed_in.get(f"/api/invoices/{inv('5001').id}").get_json()["invoice"]
    assert detail["payments"][0]["derived"] is True
    assert signed_in.get("/api/invoices/999999").status_code == 404
    csv_resp = signed_in.get("/api/reports/ar-aging.csv?as_of=2026-09-30")
    assert csv_resp.mimetype == "text/csv" and "Acme Corp" in csv_resp.get_data(as_text=True)

""" EOF - test_invoices.py """
