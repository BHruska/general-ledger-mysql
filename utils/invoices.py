"""
General Ledger v0.5.0
File: utils/invoices.py
Description: Invoices, customers and A/R aging (docs/DESIGN.md sections 8 and 9). Step A:
             reading history. Creating, issuing, voiding and payment matching follow.

invoice.amount_paid and invoice.status are maintained by this module only, from
invoice_payment rows (DESIGN.md 8.1).
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from db import SessionLocal
from models import Account, Invoice, InvoicePayment, Payee
from utils.errors import LedgerError, NotFound
from utils.money import ZERO, to_str

STATUSES = ("DRAFT", "OPEN", "PAID", "VOID")
AGING_BUCKETS = (("current", "Current"), ("d1_30", "1-30"), ("d31_60", "31-60"),
                 ("d61_90", "61-90"), ("d90_plus", "90+"))


def _customers(session) -> dict[int, Payee]:
    return {p.id: p for p in session.scalars(select(Payee).where(Payee.is_customer.is_(True)))}


def serialize(inv: Invoice, customer: Payee, accounts: dict[int, str] | None = None, full: bool = False) -> dict:
    out = {
        "id": inv.id,
        "number": inv.number,
        "customer_id": inv.customer_id,
        "customer": customer.name,
        "issue_date": inv.issue_date.isoformat(),
        "due_date": inv.due_date.isoformat(),
        "terms": inv.terms,
        "status": inv.status,
        "total": to_str(inv.total),
        "amount_paid": to_str(inv.amount_paid),
        "balance": to_str(inv.balance),
        "paid_on": inv.paid_on.isoformat() if inv.paid_on else None,
        "source": inv.source,
        "entry_id": inv.entry_id,
        "overdue": inv.status == "OPEN" and inv.due_date < date.today(),
    }
    if full:
        out["memo"] = inv.memo
        out["customer_email"] = customer.email
        out["customer_address"] = customer.address
        out["lines"] = [{"line_no": l.line_no, "description": l.description, "quantity": str(l.quantity),
                         "rate": to_str(l.rate), "amount": to_str(l.amount),
                         "income_account_id": l.income_account_id,
                         "income_account": (accounts or {}).get(l.income_account_id)} for l in inv.lines]
        out["payments"] = [{"paid_on": p.paid_on.isoformat(), "amount": to_str(p.amount), "entry_id": p.entry_id,
                            "derived": p.source == "QBO_DERIVED"} for p in inv.payments]
    return out


def list_invoices(status: str | None = None, customer_id: int | None = None) -> dict:
    if status and status not in STATUSES:
        raise LedgerError(f"Unknown status {status!r}.")
    with SessionLocal() as session:
        stmt = select(Invoice).order_by(Invoice.issue_date.desc(), Invoice.number.desc())
        if status:
            stmt = stmt.where(Invoice.status == status)
        if customer_id:
            stmt = stmt.where(Invoice.customer_id == customer_id)
        customers = _customers(session)
        rows = [serialize(i, customers[i.customer_id]) for i in session.scalars(stmt)]
        counts = dict(session.execute(select(Invoice.status, func.count()).group_by(Invoice.status)).all())
        open_total = session.scalar(select(func.coalesce(func.sum(Invoice.total - Invoice.amount_paid), 0))
                                    .where(Invoice.status == "OPEN"))
        return {"invoices": rows, "counts": {s: counts.get(s, 0) for s in STATUSES},
                "open_total": to_str(Decimal(open_total))}


def get_invoice(invoice_id: int) -> dict:
    with SessionLocal() as session:
        inv = session.get(Invoice, invoice_id)
        if inv is None:
            raise NotFound(f"Invoice {invoice_id} does not exist.")
        accounts = {a.id: f"{a.number} {a.name}" for a in session.scalars(select(Account))}
        return serialize(inv, session.get(Payee, inv.customer_id), accounts, full=True)


def list_customers() -> dict:
    """Customers with their invoice count, open balance and last invoice."""
    with SessionLocal() as session:
        stats = {cid: (n, open_, last) for cid, n, open_, last in session.execute(
            select(Invoice.customer_id, func.count(),
                   func.coalesce(func.sum(func.if_(Invoice.status == "OPEN", Invoice.total - Invoice.amount_paid, 0)), 0),
                   func.max(Invoice.issue_date))
            .group_by(Invoice.customer_id)).all()}
        out = []
        for c in sorted(_customers(session).values(), key=lambda c: c.name.casefold()):
            n, open_, last = stats.get(c.id, (0, ZERO, None))
            out.append({"id": c.id, "name": c.name, "email": c.email, "address": c.address,
                        "is_active": c.is_active, "invoices": n, "open_balance": to_str(Decimal(open_)),
                        "last_invoice": last.isoformat() if last else None})
        return {"customers": out}


def ar_aging(as_of: date) -> dict:
    """Open invoice balances at `as_of`, by customer, in days past due.

    Balances are computed at the date, not taken from today's status: an invoice paid
    after `as_of` was still open on it. Voided and draft invoices never owe anything.
    """
    with SessionLocal() as session:
        invoices = session.scalars(select(Invoice).where(
            Invoice.status.in_(("OPEN", "PAID")), Invoice.issue_date <= as_of)).all()
        paid = dict(session.execute(
            select(InvoicePayment.invoice_id, func.sum(InvoicePayment.amount))
            .where(InvoicePayment.paid_on <= as_of).group_by(InvoicePayment.invoice_id)).all())
        customers = _customers(session)

        by_customer: dict[int, dict] = {}
        detail = []
        for inv in invoices:
            # QuickBooks history can say an amount was paid that no exported payment
            # accounts for (5090, part of 5107). That part has no date, so it is treated as
            # settled from the start rather than shown as owed forever.
            placed = sum((p.amount for p in inv.payments), ZERO)
            unplaced = max(inv.amount_paid - placed, ZERO)
            balance = inv.total - unplaced - Decimal(paid.get(inv.id, 0))
            if balance <= 0:
                continue
            days = (as_of - inv.due_date).days
            bucket = ("current" if days <= 0 else "d1_30" if days <= 30 else "d31_60" if days <= 60
                      else "d61_90" if days <= 90 else "d90_plus")
            row = by_customer.setdefault(inv.customer_id, {k: ZERO for k, _ in AGING_BUCKETS})
            row[bucket] += balance
            detail.append({"invoice_id": inv.id, "number": inv.number, "customer": customers[inv.customer_id].name,
                           "issue_date": inv.issue_date.isoformat(), "due_date": inv.due_date.isoformat(),
                           "days_past_due": max(days, 0), "bucket": bucket, "balance": to_str(balance)})

        rows, totals = [], {k: ZERO for k, _ in AGING_BUCKETS}
        for cid, buckets in sorted(by_customer.items(), key=lambda kv: customers[kv[0]].name.casefold()):
            for k in totals:
                totals[k] += buckets[k]
            rows.append({"customer_id": cid, "customer": customers[cid].name,
                         **{k: to_str(v) for k, v in buckets.items()},
                         "total": to_str(sum(buckets.values(), ZERO))})
        return {"as_of": as_of.isoformat(), "buckets": [{"key": k, "label": l} for k, l in AGING_BUCKETS],
                "rows": rows, "totals": {**{k: to_str(v) for k, v in totals.items()},
                                         "total": to_str(sum(totals.values(), ZERO))},
                "detail": sorted(detail, key=lambda d: (d["customer"], d["due_date"]))}

""" EOF - invoices.py """
