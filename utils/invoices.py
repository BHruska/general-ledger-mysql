"""
General Ledger v0.5.1
File: utils/invoices.py
Description: Invoices, customers and A/R aging (docs/DESIGN.md sections 8 and 9): drafts,
             issue (Dr A/R, Cr income), void (a reversal; the number is kept), payments
             recorded against invoices, and the history imported from QuickBooks.

invoice.amount_paid and invoice.status are maintained by this module only, from
invoice_payment rows (DESIGN.md 8.1).
"""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import func, select

import config
from db import SessionLocal
from models import Account, Invoice, InvoiceLine, InvoicePayment, Payee, Settings
from utils import audit, journal
from utils.errors import LedgerError, NotFound
from utils.journal import JournalError, LineInput
from utils.money import CENT, ZERO, parse_amount, parse_date, parse_optional_date, to_str

STATUSES = ("DRAFT", "OPEN", "PAID", "VOID")
AGING_BUCKETS = (("current", "Current"), ("d1_30", "1-30"), ("d31_60", "31-60"),
                 ("d61_90", "61-90"), ("d90_plus", "90+"))


def _customers(session) -> dict[int, Payee]:
    return {p.id: p for p in session.scalars(select(Payee).where(Payee.is_customer.is_(True)))}


def serialize(inv: Invoice, customer: Payee, accounts: dict[int, str] | None = None, full: bool = False) -> dict:
    out = {
        "id": inv.id,
        "number": inv.number,
        "label": inv.number or f"Draft {inv.id}",
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
        # Drafts (no number yet) first, then newest.
        stmt = select(Invoice).order_by(Invoice.number.is_(None).desc(), Invoice.issue_date.desc(),
                                        Invoice.number.desc())
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



# ---------------------------------------------------------------- drafts

DESCRIPTION_MAX = 255


def _quantity(value, n: int) -> Decimal:
    if isinstance(value, (bool, float)):
        raise LedgerError(f"Line {n} quantity must be sent as a string.")
    try:
        q = Decimal(str(value).strip() or "1")
    except InvalidOperation:
        raise LedgerError(f"Line {n} quantity is not a number.") from None
    if not q.is_finite() or q < 0 or q != q.quantize(CENT):
        raise LedgerError(f"Line {n} quantity must be zero or more, with at most two decimals.")
    return q.quantize(CENT)


def _lines(session, raw, default_income: int | None) -> tuple[list[dict], list[str], list]:
    """Invoice lines from the editor. Amount = quantity x rate, rounded half-up, always
    computed here (DESIGN.md section 4): the page never sends a total. The third value
    is an amount (or None) for every row as sent, so the editor can show each row's."""
    if not isinstance(raw, list):
        return [], ["lines must be a list."], []
    income_ids = set(session.scalars(select(Account.id).where(Account.type == "INCOME",
                                                              Account.is_active.is_(True))))
    headers = set(session.scalars(select(Account.parent_id).where(Account.parent_id.isnot(None))))
    out, problems, row_amounts = [], [], []
    for n, line in enumerate(raw, start=1):
        row_amounts.append(None)
        if not isinstance(line, dict):
            problems.append(f"Line {n} is malformed.")
            continue
        description = (line.get("description") or "").strip()
        if not description and not str(line.get("rate") or "").strip():
            continue  # a blank row in the editor
        try:
            quantity = _quantity(line.get("quantity", "1"), n)
            rate = parse_amount(line.get("rate"), f"Line {n} rate")
        except LedgerError as e:
            problems.append(str(e))
            continue
        row_amounts[-1] = (quantity * rate).quantize(CENT, ROUND_HALF_UP)
        if not description:
            problems.append(f"Line {n} has no description.")
        elif len(description) > DESCRIPTION_MAX:
            problems.append(f"Line {n} description is longer than {DESCRIPTION_MAX} characters.")
        if rate < 0:
            problems.append(f"Line {n} rate is negative.")
        account = line.get("income_account_id") or default_income
        if not account or int(account) not in income_ids or int(account) in headers:
            problems.append(f"Line {n} needs an active income account (not a header).")
            continue
        out.append({"description": description, "quantity": quantity, "rate": rate,
                    "amount": row_amounts[-1], "income_account_id": int(account)})
    return out, problems, row_amounts


def _customer(session, customer_id) -> Payee:
    customer = session.get(Payee, int(customer_id)) if customer_id else None
    if customer is None or not customer.is_customer:
        raise LedgerError("Choose a customer.")
    return customer


def _draft_fields(session, data: dict) -> tuple[dict, list[dict], list[str], list]:
    problems = []
    settings = session.get(Settings, 1)
    try:
        customer = _customer(session, data.get("customer_id"))
    except LedgerError as e:
        customer, problems = None, [str(e)]
    try:
        issued = parse_date(data.get("issue_date"), "Issue date")
    except LedgerError as e:
        issued = date.today()
        problems.append(str(e))
    try:
        due = parse_optional_date(data.get("due_date"), "Due date")
    except LedgerError as e:
        due = None
        problems.append(str(e))
    if due is None:
        due = issued + timedelta(days=customer.payment_terms_days if customer else 15)
    if due < issued:
        problems.append("The due date is before the issue date.")
    memo = (data.get("memo") or "").strip() or None
    lines, line_problems, row_amounts = _lines(session, data.get("lines"), settings.default_income_account_id)
    problems += line_problems
    if not lines and not line_problems:
        problems.append("An invoice needs at least one line.")
    fields = {"customer_id": customer.id if customer else None, "issue_date": issued, "due_date": due,
              "terms": (data.get("terms") or "").strip()[:40] or None, "memo": memo}
    return fields, lines, problems, row_amounts


def check_draft(data: dict) -> dict:
    """The editor's live check: totals and every problem. Saves nothing."""
    with SessionLocal() as session:
        fields, lines, problems, row_amounts = _draft_fields(session, data)
        return {"ok": not problems, "problems": problems,
                "row_amounts": [to_str(a) for a in row_amounts],
                "total": to_str(sum((l["amount"] for l in lines), ZERO)),
                "due_date": fields["due_date"].isoformat()}


def save_draft(data: dict, invoice_id: int | None = None) -> dict:
    """Create or replace a draft. Drafts can be edited and deleted freely (DESIGN.md 8.1):
    they have no number and no journal entry."""
    with SessionLocal.begin() as session:
        fields, lines, problems, _ = _draft_fields(session, data)
        if problems:
            raise JournalError(problems)
        if invoice_id is None:
            inv = Invoice(status="DRAFT", source="LEDGER", amount_paid=ZERO, **fields)
            session.add(inv)
            session.flush()
        else:
            inv = session.get(Invoice, invoice_id)
            if inv is None:
                raise NotFound(f"Invoice {invoice_id} does not exist.")
            if inv.status != "DRAFT":
                raise LedgerError("Only a draft can be edited; an issued invoice is voided instead.")
            for k, v in fields.items():
                setattr(inv, k, v)
            session.query(InvoiceLine).filter(InvoiceLine.invoice_id == inv.id).delete()
        for n, l in enumerate(lines, start=1):
            session.add(InvoiceLine(invoice_id=inv.id, line_no=n, **l))
        inv.total = sum((l["amount"] for l in lines), ZERO)
        session.flush()
        return {"id": inv.id}


def delete_draft(invoice_id: int) -> None:
    with SessionLocal.begin() as session:
        inv = session.get(Invoice, invoice_id)
        if inv is None:
            raise NotFound(f"Invoice {invoice_id} does not exist.")
        if inv.status != "DRAFT":
            raise LedgerError("Only a draft can be deleted; an issued invoice is voided, keeping its number.")
        session.query(InvoiceLine).filter(InvoiceLine.invoice_id == inv.id).delete()
        session.delete(inv)


# ---------------------------------------------------------------- issue and void

def _pdf_dir() -> Path:
    return Path(config.DATA_DIR) / "invoices"


def issue(invoice_id: int) -> dict:
    """Number it and post Dr A/R / Cr income, one line per income account (DESIGN.md 8.1).

    The next number is taken under a row lock on settings, so two issues can never get
    the same one; a failed posting rolls the number back with everything else.
    """
    from utils import invoice_pdf

    with SessionLocal.begin() as session:
        inv = session.execute(select(Invoice).where(Invoice.id == invoice_id).with_for_update()).scalar_one_or_none()
        if inv is None:
            raise NotFound(f"Invoice {invoice_id} does not exist.")
        if inv.status != "DRAFT":
            raise LedgerError(f"Invoice {inv.number} is already issued.")
        if inv.total <= 0:
            raise LedgerError("An invoice must total more than 0.00 to be issued.")
        settings = session.execute(select(Settings).where(Settings.id == 1).with_for_update()).scalar_one()
        customer = session.get(Payee, inv.customer_id)
        number = f"{settings.invoice_prefix}{settings.next_invoice_seq}"
        if session.scalar(select(func.count()).select_from(Invoice).where(Invoice.number == number)):
            raise LedgerError(f"Invoice number {number} is already used; check Setup -> Settings.")

        by_account: dict[int, Decimal] = {}
        for line in inv.lines:
            by_account[line.income_account_id] = by_account.get(line.income_account_id, ZERO) + line.amount
        entry = journal.post_entry(
            session, entry_date=inv.issue_date, source="INVOICE", payee_id=customer.id,
            memo=f"Invoice {number} - {customer.name}"[:journal.MEMO_MAX],
            lines=[LineInput(settings.ar_account_id, inv.total)]
            + [LineInput(acct, -amount) for acct, amount in by_account.items() if amount])
        inv.number = number
        inv.status = "OPEN"
        inv.entry_id = entry.id
        settings.next_invoice_seq += 1
        if customer.last_used_on is None or customer.last_used_on < inv.issue_date:
            customer.last_used_on = inv.issue_date
        customer.is_active = True
        session.flush()

        # The PDF as issued is kept under /data (backed up nightly): the record of what the
        # customer was sent, even if a setting like the address changes later.
        pdf = invoice_pdf.render(session, inv)
        target = _pdf_dir() / f"{number}.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.tmp")
        tmp.write_bytes(pdf)
        tmp.replace(target)
        inv.pdf_path = f"invoices/{number}.pdf"
        audit.record(session, "invoice.issue", "invoice", inv.id,
                     {"number": number, "entry_id": entry.id, "total": to_str(inv.total)})
        return {"id": inv.id, "number": number, "entry_id": entry.id}


def void(invoice_id: int) -> dict:
    """Reverse the issue entry and keep the invoice, number and all, marked VOID (8.1)."""
    with SessionLocal.begin() as session:
        inv = session.execute(select(Invoice).where(Invoice.id == invoice_id).with_for_update()).scalar_one_or_none()
        if inv is None:
            raise NotFound(f"Invoice {invoice_id} does not exist.")
        if inv.status == "DRAFT":
            raise LedgerError("A draft is deleted, not voided.")
        if inv.status == "VOID":
            raise LedgerError(f"Invoice {inv.number} is already void.")
        if inv.source != "LEDGER" or inv.entry_id is None:
            raise LedgerError(f"Invoice {inv.number} is QuickBooks history; it was never posted here to reverse.")
        if inv.amount_paid:
            raise LedgerError(f"Invoice {inv.number} has payments; undo them on the Review page first.")
        reversal = journal.reverse_entry(session, inv.entry_id, reversal_date=max(date.today(), inv.issue_date),
                                         memo=f"Void of invoice {inv.number}", allow_sources={"INVOICE"})
        inv.status = "VOID"
        audit.record(session, "invoice.void", "invoice", inv.id,
                     {"number": inv.number, "reversal_entry_id": reversal.id})
        return {"id": inv.id, "number": inv.number, "reversal_entry_id": reversal.id}


def pdf_bytes(invoice_id: int) -> tuple[bytes, str]:
    """The PDF as issued if one was kept, else rendered now (drafts, and history)."""
    from utils import invoice_pdf

    with SessionLocal() as session:
        inv = session.get(Invoice, invoice_id)
        if inv is None:
            raise NotFound(f"Invoice {invoice_id} does not exist.")
        name = f"invoice-{inv.number}.pdf" if inv.number else f"invoice-draft-{inv.id}.pdf"
        if inv.pdf_path:
            stored = Path(config.DATA_DIR) / inv.pdf_path
            if stored.is_file():
                return stored.read_bytes(), name
        return invoice_pdf.render(session, inv), name


# ---------------------------------------------------------------- payments

def open_invoices() -> list[dict]:
    """Invoices a receipt could pay, for the review page's "Pay invoice" choice."""
    with SessionLocal() as session:
        customers = _customers(session)
        rows = session.scalars(select(Invoice).where(Invoice.status == "OPEN").order_by(Invoice.due_date)).all()
        return [serialize(i, customers[i.customer_id]) for i in rows if i.balance > 0]


def apply_payment(session, invoice_id: int, entry_id: int, paid_on: date, amount: Decimal) -> Invoice:
    """Record a receipt against an invoice. Does not commit. amount_paid and status are
    maintained here and nowhere else (DESIGN.md 8.1)."""
    inv = session.execute(select(Invoice).where(Invoice.id == invoice_id).with_for_update()).scalar_one_or_none()
    if inv is None:
        raise NotFound(f"Invoice {invoice_id} does not exist.")
    if inv.status != "OPEN":
        raise LedgerError(f"Invoice {inv.number} is {inv.status.lower()}; only an open invoice takes payments.")
    if amount <= 0:
        raise LedgerError("A payment must be more than 0.00.")
    if amount > inv.balance:
        raise LedgerError(f"{to_str(amount)} is more than invoice {inv.number}'s balance of {to_str(inv.balance)}; "
                          "split the deposit to post the rest elsewhere.")
    session.add(InvoicePayment(invoice_id=inv.id, entry_id=entry_id, paid_on=paid_on, amount=amount, source="LEDGER"))
    inv.amount_paid += amount
    if inv.balance == 0:
        inv.status, inv.paid_on = "PAID", paid_on
    session.flush()
    return inv


def remove_payments_for_entry(session, entry_id: int) -> list[str]:
    """An undone bank posting takes its invoice payments with it. Does not commit."""
    numbers = []
    for p in session.scalars(select(InvoicePayment).where(InvoicePayment.entry_id == entry_id)).all():
        inv = session.execute(select(Invoice).where(Invoice.id == p.invoice_id).with_for_update()).scalar_one()
        inv.amount_paid -= p.amount
        inv.status, inv.paid_on = "OPEN", None
        numbers.append(inv.number)
        session.delete(p)
    session.flush()
    return numbers


# ---------------------------------------------------------------- customers

def create_customer(data: dict) -> dict:
    name = " ".join((data.get("name") or "").split())
    if not name:
        raise LedgerError("The customer needs a name.")
    if len(name) > 120:
        raise LedgerError("The name is longer than 120 characters.")
    with SessionLocal.begin() as session:
        existing = session.scalar(select(Payee).where(Payee.name == name))
        if existing:
            if existing.is_customer:
                raise LedgerError(f"{existing.name} is already a customer.")
            existing.is_customer = True  # a vendor who is now also invoiced
            existing.is_active = True
            customer = existing
        else:
            customer = Payee(name=name, is_customer=True, is_vendor=False, is_active=True)
            session.add(customer)
        customer.email = (data.get("email") or "").strip() or customer.email
        customer.address = (data.get("address") or "").strip() or customer.address
        session.flush()
        audit.record(session, "customer.create", "payee", customer.id, {"name": customer.name})
        return {"id": customer.id, "name": customer.name}

""" EOF - invoices.py """

