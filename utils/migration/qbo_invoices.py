"""
General Ledger v0.5.0
File: utils/migration/qbo_invoices.py
Description: Invoice history from QuickBooks Online (docs/DESIGN.md sections 8 and 10).

Inputs, all CSV exports:
  Sales by Product/Service Detail (All Dates)   every invoice line: the invoices themselves
  Invoices and Received Payments (All Dates)    each customer's payments (date, amount)
  Open Invoices                                 what is unpaid, with terms and due dates
  Customer Contact List                         emails and billing addresses

Decisions confirmed by the owner on 2026-09-30:
  - history never posts: QuickBooks already recorded that income, and it reaches this
    ledger once, through the opening balances at cutover;
  - Open Invoices is the authority on what is unpaid;
  - QuickBooks does not say which payment paid which invoice, so each customer's payments
    are applied to their oldest invoices first and marked QBO_DERIVED;
  - numbering continues QuickBooks' own sequence.
"""

import csv
import io
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import func, select

from db import SessionLocal
from models import Account, Invoice, InvoiceLine, InvoicePayment, Payee, Settings
from utils import audit
from utils.errors import LedgerError
from utils.migration.qbo_payees import _account_lookup, _key

CENT = Decimal("0.01")
SALES_HEADER = ["", "Transaction date", "Transaction type", "Num", "Customer full name", "Description",
                "Quantity", "Sales price", "Amount", "Balance"]
IRP_HEADER = ["", "Date", "Transaction type", "Memo/Description", "Transaction number", "Amount"]
OPEN_HEADER = ["", "Date", "Transaction type", "Num", "Term", "Due date", "Open balance"]
CUSTOMER_HEADER = ["Customer full name", "Phone numbers", "Email", "Full name", "Bill address", "Ship address"]
DEFAULT_INCOME_ACCOUNT = "Website Hosting"


def _rows(content: str, header: list[str], what: str) -> list[list[str]]:
    rows = list(csv.reader(io.StringIO(content.lstrip("﻿"))))
    for i, r in enumerate(rows):
        if [c.strip() for c in r[:len(header)]] == header:
            return rows[i + 1:]
    raise LedgerError(f"This is not a QuickBooks Online {what} export.")


def _money(text: str) -> Decimal | None:
    text = (text or "").replace(",", "").replace("$", "").strip()
    if not text:
        return None
    try:
        return Decimal(text).quantize(CENT)
    except InvalidOperation:
        raise LedgerError(f"Not an amount: {text!r}") from None


def _date(text: str) -> date:
    return datetime.strptime(text.strip(), "%m/%d/%Y").date()


@dataclass
class QboLine:
    product: str
    description: str
    quantity: Decimal
    rate: Decimal
    amount: Decimal


@dataclass
class QboInvoice:
    number: str
    customer: str
    issue_date: date
    lines: list[QboLine] = field(default_factory=list)
    due_date: date | None = None
    terms: str | None = None
    open_balance: Decimal = Decimal("0.00")

    @property
    def total(self) -> Decimal:
        return sum((l.amount for l in self.lines), Decimal("0.00"))


def parse_sales(content: str) -> dict[str, QboInvoice]:
    invoices: dict[str, QboInvoice] = {}
    product = None
    for r in _rows(content, SALES_HEADER, "Sales by Product/Service Detail"):
        if not r or not any(c.strip() for c in r):
            continue
        if r[0].strip():
            product = None if r[0].startswith(("Total for", "TOTAL")) else r[0].strip()
            continue
        if len(r) < 9 or r[2].strip() != "Invoice":
            continue
        number, customer = r[3].strip(), r[4].strip()
        amount = _money(r[8]) or Decimal("0.00")
        qty = _money(r[6])
        rate = _money(r[7])
        if qty is None:
            qty = Decimal("1.00") if amount else Decimal("0.00")
        if rate is None:
            rate = (amount / qty).quantize(CENT, ROUND_HALF_UP) if qty else Decimal("0.00")
        inv = invoices.setdefault(number, QboInvoice(number, customer, _date(r[1])))
        if inv.customer != customer:
            raise LedgerError(f"Invoice {number} has lines for two customers.")
        inv.lines.append(QboLine(product or "", (r[5].strip() or product or "Services")[:255], qty, rate, amount))
    if not invoices:
        raise LedgerError("The Sales by Product/Service Detail export has no invoices.")
    return invoices


def parse_payments(content: str) -> dict[str, list[tuple[date, Decimal]]]:
    """Each customer's payments. A negative "Deposit" row or a payment with no amount is
    QuickBooks bookkeeping noise, not money received, and is skipped."""
    payments: dict[str, list[tuple[date, Decimal]]] = defaultdict(list)
    customer = None
    for r in _rows(content, IRP_HEADER, "Invoices and Received Payments"):
        if not r or not any(c.strip() for c in r):
            continue
        if r[0].strip():
            customer = None if r[0].startswith(("Total for", "TOTAL")) or any(c.strip() for c in r[1:]) else r[0].strip()
            continue
        if customer and len(r) > 5 and r[2].strip() == "Payment":
            amount = _money(r[5])
            if amount and amount > 0:
                payments[_key(customer)].append((_date(r[1]), amount))
    return payments


def parse_open(content: str) -> dict[str, tuple[date, str, Decimal]]:
    out = {}
    for r in _rows(content, OPEN_HEADER, "Open Invoices"):
        if len(r) > 6 and not r[0].strip() and r[2].strip() == "Invoice":
            out[r[3].strip()] = (_date(r[5]) if r[5].strip() else _date(r[1]), r[4].strip() or None, _money(r[6]))
    return out


def parse_customers(content: str) -> dict[str, dict]:
    out = {}
    for r in _rows(content, CUSTOMER_HEADER, "Customer Contact List"):
        if len(r) < 5 or not r[0].strip() or r[0].strip().startswith(" "):
            continue
        out[_key(r[0])] = {"email": r[2].strip() or None, "address": r[4].strip() or None}
    return out


@dataclass
class Plan:
    invoices: list[QboInvoice]
    allocations: dict[str, list[tuple[date, Decimal]]]   # invoice number -> (paid_on, amount)
    unallocated: dict[str, Decimal]                       # customer -> payment money left over
    short: dict[str, Decimal]                             # invoice -> paid per QBO but no payment found
    customers: dict[str, dict]
    next_number: int


def plan(sales_csv: str, payments_csv: str, open_csv: str, customers_csv: str) -> Plan:
    invoices = parse_sales(sales_csv)
    open_ = parse_open(open_csv)
    missing = set(open_) - set(invoices)
    if missing:
        raise LedgerError(f"Open invoices {sorted(missing)} are not in the Sales detail export.")
    for number, (due, terms, balance) in open_.items():
        inv = invoices[number]
        inv.due_date, inv.terms, inv.open_balance = due, terms, balance
    for inv in invoices.values():
        inv.due_date = inv.due_date or inv.issue_date

    payments = parse_payments(payments_csv)
    allocations: dict[str, list] = defaultdict(list)
    unallocated, short = {}, {}
    by_customer: dict[str, list[QboInvoice]] = defaultdict(list)
    for inv in invoices.values():
        by_customer[_key(inv.customer)].append(inv)
    for ckey, invs in by_customer.items():
        # Oldest first, then by number: the order a customer would have paid them in.
        queue = sorted(invs, key=lambda i: (i.issue_date, int(i.number) if i.number.isdigit() else 0))
        owed = {i.number: i.total - i.open_balance for i in queue}
        for when, amount in sorted(payments.get(ckey, [])):
            left = amount
            for inv in queue:
                if left <= 0:
                    break
                take = min(left, owed[inv.number])
                if take > 0:
                    allocations[inv.number].append((when, take))
                    owed[inv.number] -= take
                    left -= take
            if left > 0:
                unallocated[ckey] = unallocated.get(ckey, Decimal("0.00")) + left
        for inv in queue:
            if owed[inv.number] > 0:
                short[inv.number] = owed[inv.number]

    numbers = [int(n) for n in invoices if n.isdigit()]
    return Plan(list(invoices.values()), allocations, unallocated, short,
                parse_customers(customers_csv), (max(numbers) + 1) if numbers else 1)


def summary(p: Plan) -> dict:
    open_ = [i for i in p.invoices if i.open_balance > 0]
    return {
        "invoices": len(p.invoices),
        "customers": len({_key(i.customer) for i in p.invoices}),
        "lines": sum(len(i.lines) for i in p.invoices),
        "total_invoiced": str(sum((i.total for i in p.invoices), Decimal("0.00"))),
        "open": [{"number": i.number, "customer": i.customer, "balance": str(i.open_balance),
                  "due_date": i.due_date.isoformat()} for i in open_],
        "open_total": str(sum((i.open_balance for i in open_), Decimal("0.00"))),
        "payments_applied": sum(len(v) for v in p.allocations.values()),
        # Paid according to QuickBooks, but no payment in the export covers it (a payment
        # recorded some other way). Imported as paid; shown here so it is not a surprise.
        "paid_without_matching_payment": {k: str(v) for k, v in sorted(p.short.items())},
        "payment_money_left_over": {k: str(v) for k, v in p.unallocated.items()},
        "next_number": p.next_number,
    }


def preview(sales_csv, payments_csv, open_csv, customers_csv) -> dict:
    return summary(plan(sales_csv, payments_csv, open_csv, customers_csv))


def apply(sales_csv, payments_csv, open_csv, customers_csv, *, active_since: date,
          income_account_number: str | None = None, replace: bool = False) -> dict:
    p = plan(sales_csv, payments_csv, open_csv, customers_csv)
    with SessionLocal.begin() as session:
        existing = session.scalar(select(func.count()).select_from(Invoice))
        if existing:
            if not replace:
                raise LedgerError(f"{existing} invoices already exist. Re-run with --replace to start over.")
            if session.scalar(select(func.count()).select_from(Invoice).where(Invoice.source == "LEDGER")):
                raise LedgerError("Invoices created in this ledger exist; QuickBooks history cannot be replaced.")
            ids = list(session.scalars(select(Invoice.id)))
            session.query(InvoicePayment).filter(InvoicePayment.invoice_id.in_(ids)).delete(synchronize_session=False)
            session.query(InvoiceLine).filter(InvoiceLine.invoice_id.in_(ids)).delete(synchronize_session=False)
            session.query(Invoice).delete(synchronize_session=False)

        accounts = session.scalars(select(Account)).all()
        if income_account_number:
            income = next((a for a in accounts if a.number == income_account_number), None)
        else:
            income_id = _account_lookup(accounts).get(DEFAULT_INCOME_ACCOUNT)
            income = next((a for a in accounts if a.id == income_id), None)
        if income is None or income.type != "INCOME":
            raise LedgerError("Could not find the income account for invoice lines; pass --income-account NUMBER.")

        payees = {_key(pe.name): pe for pe in session.scalars(select(Payee))}
        for inv in sorted(p.invoices, key=lambda i: (i.issue_date, i.number)):
            ckey = _key(inv.customer)
            customer = payees.get(ckey)
            if customer is None:
                customer = Payee(name=" ".join(inv.customer.split())[:120], is_customer=True, is_vendor=False,
                                 is_active=True)
                session.add(customer)
                session.flush()
                payees[ckey] = customer
            customer.is_customer = True
            contact = p.customers.get(ckey, {})
            customer.email = customer.email or contact.get("email")
            customer.address = customer.address or contact.get("address")
            last = max([inv.issue_date] + [d for d, _ in p.allocations.get(inv.number, [])])
            if customer.last_used_on is None or customer.last_used_on < last:
                customer.last_used_on = last
            if customer.last_used_on >= active_since:
                customer.is_active = True

            paid = inv.total - inv.open_balance
            allocations = p.allocations.get(inv.number, [])
            completed = allocations[-1][0] if allocations and inv.open_balance == 0 and inv.number not in p.short else None
            row = Invoice(number=inv.number, customer_id=customer.id, issue_date=inv.issue_date,
                          due_date=inv.due_date, terms=inv.terms,
                          status="OPEN" if inv.open_balance > 0 else "PAID",
                          total=inv.total, amount_paid=paid, paid_on=completed, source="QBO")
            session.add(row)
            session.flush()
            for n, line in enumerate(inv.lines, start=1):
                session.add(InvoiceLine(invoice_id=row.id, line_no=n, description=line.description,
                                        quantity=line.quantity, rate=line.rate, amount=line.amount,
                                        income_account_id=income.id))
            for when, amount in allocations:
                session.add(InvoicePayment(invoice_id=row.id, entry_id=None, paid_on=when, amount=amount,
                                           source="QBO_DERIVED"))

        settings = session.get(Settings, 1)
        settings.next_invoice_seq = max(settings.next_invoice_seq or 1, p.next_number)
        settings.default_income_account_id = settings.default_income_account_id or income.id
        s = summary(p)
        audit.record(session, "invoices.import_qbo", "invoice", None,
                     {k: v for k, v in s.items() if k in ("invoices", "customers", "lines", "open_total", "next_number")})
        return s

""" EOF - qbo_invoices.py """
