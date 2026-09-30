"""
General Ledger v0.5.1
File: tests/test_invoicing.py
Description: Invoicing step B (docs/DESIGN.md section 8): drafts, issue (numbered, posted
             Dr A/R / Cr income, PDF kept), void, and deposits matched to and posted
             against open invoices.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

import config
import db
from models import BankTxn, Invoice, JournalEntry, Settings
from utils import bank_accounts, bank_queue, invoices, journal, settings_manager
from utils.errors import LedgerError
from utils.feeds import file_import
from utils.journal import JournalError

CHECKING_CSV = (Path(__file__).resolve().parent / "fixtures" / "chase_checking.csv").read_text()


@pytest.fixture(autouse=True)
def books_always_balance():
    yield
    with db.SessionLocal() as session:
        assert journal.journal_total(session) == 0


@pytest.fixture
def setup(chart):
    with db.SessionLocal.begin() as session:
        s = session.get(Settings, 1)
        s.next_invoice_seq, s.default_income_account_id = 5115, chart["4000"]
        s.company_name, s.zelle_recipient, s.zelle_display_name = "Example Co, LLC", "pay@example.com", "Example Co, LLC"
    customer = invoices.create_customer({"name": "Example Customer", "email": "ap@example.org",
                                         "address": "1 Main St\nSpringfield, IL"})["id"]
    return {"customer": customer, **chart}


def draft(setup, lines=None, **kw):
    return invoices.save_draft({"customer_id": setup["customer"], "issue_date": "2026-09-01", "terms": "Net 15",
                                "lines": lines or [{"description": "Web Site Hosting 2026", "quantity": "1", "rate": "1200"},
                                                   {"description": "Help, hours", "quantity": "2.5", "rate": "100.00"}], **kw})["id"]


def get(invoice_id) -> Invoice:
    with db.SessionLocal() as session:
        return session.get(Invoice, invoice_id)


# ------------------------------------------------------------------ drafts

def test_check_computes_amounts_and_lists_problems(setup):
    c = invoices.check_draft({"customer_id": setup["customer"], "issue_date": "2026-09-01", "lines": [
        {"description": "Hosting", "quantity": "3", "rate": "33.33"}, {"description": "", "rate": ""},
        {"description": "Bad", "quantity": "x", "rate": "5"}]})
    assert c["row_amounts"] == ["99.99", None, None] and c["total"] == "99.99"
    assert c["due_date"] == "2026-09-16"  # the customer's payment terms (15 days)
    assert not c["ok"] and any("quantity" in p for p in c["problems"])
    none = invoices.check_draft({"issue_date": "2026-09-01", "lines": []})
    assert "Choose a customer." in none["problems"] and "An invoice needs at least one line." in none["problems"]


def test_header_income_account_refused(setup):
    with pytest.raises(JournalError, match="income account"):
        draft(setup, lines=[{"description": "x", "rate": "5", "income_account_id": setup["6100"]}])


def test_draft_has_no_number_and_posts_nothing(setup):
    inv = get(draft(setup))
    assert (inv.status, inv.number, inv.entry_id, inv.total) == ("DRAFT", None, None, Decimal("1450.00"))
    invoices.save_draft({"customer_id": setup["customer"], "issue_date": "2026-09-02",
                         "lines": [{"description": "Changed", "rate": "10"}]}, inv.id)
    assert get(inv.id).total == Decimal("10.00") and len(get(inv.id).lines) == 1
    invoices.delete_draft(inv.id)
    assert get(inv.id) is None


# ------------------------------------------------------------------ issue and void

def test_issue_numbers_posts_and_keeps_the_pdf(setup):
    r = invoices.issue(draft(setup))
    inv = get(r["id"])
    assert (inv.number, inv.status) == ("5115", "OPEN")
    with db.SessionLocal() as session:
        entry = session.get(JournalEntry, inv.entry_id)
        assert entry.source == "INVOICE" and entry.payee_id == setup["customer"]
        assert {(l.account_id, l.amount) for l in entry.lines} == {(setup["1200"], Decimal("1450.00")),
                                                                    (setup["4000"], Decimal("-1450.00"))}
        assert session.get(Settings, 1).next_invoice_seq == 5116
    pdf = Path(config.DATA_DIR) / inv.pdf_path
    assert pdf.read_bytes().startswith(b"%PDF")
    with pytest.raises(LedgerError, match="already issued"):
        invoices.issue(inv.id)
    with pytest.raises(LedgerError, match="Only a draft"):
        invoices.save_draft({"customer_id": setup["customer"], "issue_date": "2026-09-01",
                             "lines": [{"description": "x", "rate": "1"}]}, inv.id)


def test_failed_issue_does_not_use_a_number(setup):
    settings_manager.set_lock_date({"lock_date": "2026-09-15"})
    with pytest.raises(JournalError, match="lock date"):
        invoices.issue(draft(setup))
    with db.SessionLocal() as session:
        assert session.get(Settings, 1).next_invoice_seq == 5115


def test_void_reverses_and_keeps_the_number(setup):
    inv_id = invoices.issue(draft(setup))["id"]
    r = invoices.void(inv_id)
    inv = get(inv_id)
    assert (inv.status, inv.number) == ("VOID", "5115")
    with db.SessionLocal() as session:
        assert session.get(JournalEntry, inv.entry_id).reversed_by_entry_id == r["reversal_entry_id"]
    assert invoices.issue(draft(setup))["number"] == "5116"   # the voided number is not reused


# ------------------------------------------------------------------ deposits pay invoices

@pytest.fixture
def checking(setup):
    return bank_accounts.create_file_account({"gl_account_id": setup["1010"], "name": "Checking",
                                              "feed_start_date": "2026-07-01"})["id"]


def zelle_line() -> BankTxn:
    with db.SessionLocal() as session:
        return next(t for t in session.scalars(select(BankTxn)) if t.description.startswith("Zelle payment"))


def test_amount_and_name_suggest_the_invoice(setup, checking):
    inv_id = invoices.issue(draft(setup, lines=[{"description": "Hosting", "rate": "1500"}]))["id"]
    file_import.import_file(checking, CHECKING_CSV, None)
    line = zelle_line()
    assert (line.suggestion_reason, line.suggested_invoice_id, line.status) == ("INVOICE", inv_id, "SUGGESTED")


def test_invoice_number_in_the_memo_suggests_it(setup, checking):
    inv_id = invoices.issue(draft(setup, lines=[{"description": "Hosting", "rate": "2000"}]))["id"]
    memo_csv = CHECKING_CSV.replace("Zelle payment from EXAMPLE CUSTOMER 1AB2CD3EF", "Zelle payment from SOMEONE ELSE inv 5115")
    file_import.import_file(checking, memo_csv, None)
    assert zelle_line().suggested_invoice_id == inv_id and zelle_line().suggestion_reason == "INVOICE"


def test_amount_alone_is_the_weaker_match_and_only_when_unique(setup, checking):
    other = invoices.create_customer({"name": "Other Org"})["id"]
    one = invoices.issue(invoices.save_draft({"customer_id": other, "issue_date": "2026-09-01",
                                              "lines": [{"description": "x", "rate": "1500"}]})["id"])["id"]
    file_import.import_file(checking, CHECKING_CSV.replace("EXAMPLE CUSTOMER", "NOBODY WE KNOW"), None)
    assert (zelle_line().suggestion_reason, zelle_line().suggested_invoice_id) == ("INVOICE_AMOUNT", one)
    invoices.issue(invoices.save_draft({"customer_id": other, "issue_date": "2026-09-02",
                                        "lines": [{"description": "y", "rate": "1500"}]})["id"])
    bank_queue.refresh_suggestions()
    assert zelle_line().suggested_invoice_id is None      # two candidates: no guess


def test_posting_pays_the_invoice_and_undo_reopens_it(setup, checking):
    inv_id = invoices.issue(draft(setup, lines=[{"description": "Hosting", "rate": "1500"}]))["id"]
    file_import.import_file(checking, CHECKING_CSV, None)
    r = bank_queue.post_line(zelle_line().id, {"invoice_id": inv_id})
    inv = get(inv_id)
    assert (inv.status, inv.amount_paid, inv.paid_on) == ("PAID", Decimal("1500.00"), date(2026, 9, 28))
    with db.SessionLocal() as session:
        lines = {(l.account_id, l.amount) for l in session.get(JournalEntry, r["entry_id"]).lines}
    assert lines == {(setup["1010"], Decimal("1500.00")), (setup["1200"], Decimal("-1500.00"))}
    back = bank_queue.unpost(zelle_line().id)
    assert back["invoices_reopened"] == ["5115"]
    assert (get(inv_id).status, get(inv_id).amount_paid) == ("OPEN", Decimal("0.00"))
    assert zelle_line().suggested_invoice_id == inv_id     # suggested again


def test_partial_payment_and_overpayment(setup, checking):
    inv_id = invoices.issue(draft(setup, lines=[{"description": "Hosting", "rate": "3000"}]))["id"]
    file_import.import_file(checking, CHECKING_CSV, None)
    bank_queue.post_line(zelle_line().id, {"invoice_id": inv_id})
    assert (get(inv_id).status, get(inv_id).balance) == ("OPEN", Decimal("1500.00"))
    small = invoices.issue(draft(setup, lines=[{"description": "Tiny", "rate": "10"}]))["id"]
    bank_queue.unpost(zelle_line().id)
    with pytest.raises(LedgerError, match="more than invoice"):
        bank_queue.post_line(zelle_line().id, {"invoice_id": small})
    assert zelle_line().status in ("NEW", "SUGGESTED")


def test_post_all_suggested_pays_invoices(setup, checking):
    inv_id = invoices.issue(draft(setup, lines=[{"description": "Hosting", "rate": "1500"}]))["id"]
    file_import.import_file(checking, CHECKING_CSV, None)
    assert bank_queue.post_suggested()["posted"] >= 1
    assert get(inv_id).status == "PAID"


def test_void_refused_once_paid(setup, checking):
    inv_id = invoices.issue(draft(setup, lines=[{"description": "Hosting", "rate": "1500"}]))["id"]
    file_import.import_file(checking, CHECKING_CSV, None)
    bank_queue.post_line(zelle_line().id, {"invoice_id": inv_id})
    with pytest.raises(LedgerError, match="PAID|paid|payments"):
        invoices.void(inv_id)


# ------------------------------------------------------------------ pages, PDF, API

def test_pdf_for_draft_and_unicode(setup, signed_in):
    inv_id = draft(setup, lines=[{"description": "Site — “premium” hosting …", "rate": "5"}])
    resp = signed_in.get(f"/invoices/{inv_id}/pdf")
    assert resp.status_code == 200 and resp.mimetype == "application/pdf" and resp.data.startswith(b"%PDF")


def test_api_flow(setup, signed_in):
    created = signed_in.post("/api/invoices", json={"customer_id": setup["customer"], "issue_date": "2026-09-01",
                                                    "lines": [{"description": "Hosting", "rate": "100"}]}).get_json()
    inv_id = created["invoice"]["id"]
    assert signed_in.post(f"/api/invoices/{inv_id}/issue", json={}).get_json()["invoice"]["number"] == "5115"
    assert [i["number"] for i in signed_in.get("/api/invoices/open").get_json()["invoices"]] == ["5115"]
    for path in ("/invoices/new", f"/invoices/{inv_id}", f"/invoices/{inv_id}/edit", "/setup/settings"):
        assert signed_in.get(path).status_code == 200, path
    s = signed_in.get("/api/settings").get_json()["settings"]
    assert (s["zelle_recipient"], s["next_invoice_number"]) == ("pay@example.com", "5116")

""" EOF - test_invoicing.py """
