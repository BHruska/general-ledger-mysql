"""
General Ledger v0.6.0
File: utils/migration/qbo_journal.py
Description: QuickBooks Online's full history as journal entries, from its "Journal"
             report (All Dates, CSV). Every QuickBooks transaction before a boundary date
             becomes one balanced IMPORT entry, so reports here match QuickBooks for any
             past period. From the boundary on, this ledger's own postings (the bank feed)
             are the books; importing QuickBooks' entries past it would count them twice.

Decisions confirmed by the owner on 2026-09-30:
  - full history instead of DESIGN.md 10's single opening-balance entry;
  - the boundary is the bank feed's start date;
  - QuickBooks' deleted accounts come in as inactive accounts so old years add up;
  - a re-run is a rebuild: posted entries are immutable, so this refuses to run twice.

Needs the chart (qbo_chart.py) and payees (qbo_payees.py) imported first; invoices
(qbo_invoices.py) are optional and, if present, get linked to their entries.
"""

import csv
import io
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from db import SessionLocal
from models import Account, Invoice, JournalEntry, JournalLine, Payee, Settings
from utils import audit
from utils.errors import LedgerError
from utils.money import parse_amount
from utils.migration.qbo_chart import GENERAL_SUFFIX
from utils.migration.qbo_payees import _key

HEADER = ["", "Transaction date", "Transaction type", "Num", "Name", "Description", "Account Name", "Debit", "Credit"]
DELETED = " (deleted)"
MEMO_MAX = 255

# A deleted QuickBooks account has no type in any export; its name says which it was.
# (name fragment, ledger type, first number of the block to place it in)
DELETED_KINDS = [("mastercard", "LIABILITY", 2100), ("visa", "LIABILITY", 2100), ("card", "LIABILITY", 2100),
                 ("checking", "ASSET", 1010), ("bank", "ASSET", 1010), ("savings", "ASSET", 1010)]


def _money(text: str) -> Decimal:
    """A blank Debit or Credit cell is 0.00. More than two decimal places is refused,
    never rounded, as everywhere else (utils/money.py)."""
    if not (text or "").strip():
        return Decimal("0.00")
    return parse_amount(text, "QuickBooks amount")


@dataclass
class QboLine:
    account: str
    amount: Decimal          # debit positive, credit negative
    description: str


@dataclass
class QboTxn:
    qbo_id: str
    when: date
    kind: str
    number: str
    name: str
    lines: list[QboLine] = field(default_factory=list)


def parse(content: str) -> list[QboTxn]:
    rows = list(csv.reader(io.StringIO(content.lstrip("﻿"))))
    try:
        start = next(i for i, r in enumerate(rows) if [c.strip() for c in r[:len(HEADER)]] == HEADER)
    except StopIteration:
        raise LedgerError("This is not a QuickBooks Online Journal export (no Transaction date / Account Name / "
                          "Debit / Credit header).") from None
    txns: "OrderedDict[str, QboTxn]" = OrderedDict()
    current = None
    for r in rows[start + 1:]:
        if not r or not any(c.strip() for c in r):
            continue
        first = r[0].strip()
        if first:
            # A transaction opens with its QuickBooks id alone in the first column; "Total
            # for <id>", the TOTAL line and the timestamp footer all close it.
            current = first if first.replace("-", "").isdigit() else None
            continue
        if current is None or len(r) < 9 or not r[1].strip():
            continue
        when = datetime.strptime(r[1].strip(), "%m/%d/%Y").date()
        txn = txns.get(current)
        if txn is None:
            txn = txns[current] = QboTxn(current, when, r[2].strip(), r[3].strip(), r[4].strip())
        elif txn.when != when:
            raise LedgerError(f"QuickBooks transaction {current} has lines on two dates.")
        amount = _money(r[7]) - _money(r[8])
        if amount == 0:
            continue  # QuickBooks' zero placeholder lines; the ledger forbids 0.00 lines
        if not r[6].strip():
            raise LedgerError(f"QuickBooks transaction {current} has an amount with no account.")
        txn.lines.append(QboLine(r[6].strip(), amount, r[5].strip()))
    if not txns:
        raise LedgerError("The Journal export has no transactions.")
    for t in txns.values():
        if sum((l.amount for l in t.lines), Decimal("0.00")) != 0:
            raise LedgerError(f"QuickBooks transaction {t.qbo_id} does not balance.")
    return list(txns.values())


def _resolver(accounts: list[Account]):
    """QBO account name -> ledger account id, as qbo_chart.py laid the chart out: a parent
    with sub-accounts resolves to its "- General" sub-account (a header takes no postings)."""
    by_id = {a.id: a for a in accounts}
    headers = {a.parent_id for a in accounts if a.parent_id}
    generals = {a.parent_id: a.id for a in accounts if a.parent_id and a.name.endswith(GENERAL_SUFFIX)}
    lookup = {}
    for a in accounts:
        if a.parent_id is None:
            lookup[a.name] = generals.get(a.id) if a.id in headers else a.id
        elif not a.name.endswith(GENERAL_SUFFIX):
            lookup[f"{by_id[a.parent_id].name}:{a.name}"] = a.id
    return lookup


@dataclass
class Plan:
    importing: list[QboTxn]
    after_boundary: int
    all_zero: list[str]
    deleted_accounts: dict[str, int]      # name -> lines using it
    unknown_accounts: dict[str, int]
    missing_payees: set[str]
    date_range: tuple[date, date] | None


def plan(content: str, before: date) -> Plan:
    txns = parse(content)
    all_zero = [t.qbo_id for t in txns if not t.lines]
    importing = [t for t in txns if t.lines and t.when < before]
    with SessionLocal() as session:
        accounts = session.scalars(select(Account)).all()
        payees = {_key(p.name) for p in session.scalars(select(Payee))}
    lookup = _resolver(accounts)
    used = Counter(l.account for t in importing for l in t.lines)
    deleted = {a: n for a, n in used.items() if a not in lookup and a.endswith(DELETED)}
    unknown = {a: n for a, n in used.items() if a not in lookup and not a.endswith(DELETED)}
    missing = {t.name for t in importing if t.name and _key(t.name) not in payees}
    dates = [t.when for t in importing]
    return Plan(importing, sum(1 for t in txns if t.lines and t.when >= before), all_zero, deleted, unknown,
                missing, (min(dates), max(dates)) if dates else None)


def summary(p: Plan, before: date) -> dict:
    return {
        "before": before.isoformat(),
        "transactions": len(p.importing),
        "lines": sum(len(t.lines) for t in p.importing),
        "first_date": p.date_range[0].isoformat() if p.date_range else None,
        "last_date": p.date_range[1].isoformat() if p.date_range else None,
        "skipped_on_or_after_boundary": p.after_boundary,
        "skipped_all_zero": len(p.all_zero),
        "types": dict(Counter(t.kind for t in p.importing).most_common()),
        "deleted_accounts_to_create": p.deleted_accounts,
        "unknown_accounts": p.unknown_accounts,
        "payees_to_create": len(p.missing_payees),
    }


def preview(content: str, before: date) -> dict:
    return summary(plan(content, before), before)


def _place_deleted(session, name: str, taken: set[str]) -> Account:
    bare = name[: -len(DELETED)]
    kind = next(((t, first) for frag, t, first in DELETED_KINDS if frag in bare.lower()), None)
    if kind is None:
        raise LedgerError(f"Cannot tell what kind of account the deleted QuickBooks account {name!r} was.")
    type_, first = kind
    number = first
    while str(number) in taken:
        number += 10
    taken.add(str(number))
    account = Account(number=str(number), name=f"{bare} (closed)"[:100], type=type_, is_active=False,
                      is_bank_account=True, description="QuickBooks account deleted there; kept for its history")
    session.add(account)
    session.flush()
    return account


def apply(content: str, before: date) -> dict:
    p = plan(content, before)
    if p.unknown_accounts:
        raise LedgerError(f"These QuickBooks accounts are not in the chart: {p.unknown_accounts}. "
                          "Import the chart (import-qbo-chart) from the same QuickBooks company first.")
    with SessionLocal.begin() as session:
        if session.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.source == "IMPORT")):
            raise LedgerError("QuickBooks history is already imported. Posted entries are never deleted, so a "
                              "re-run is a rebuild of the database from the exports.")
        clash = session.scalar(select(func.count()).select_from(JournalEntry)
                               .where(JournalEntry.entry_date < before, JournalEntry.source != "IMPORT"))
        if clash:
            raise LedgerError(f"{clash} entries dated before {before} already exist here; history would count them "
                              "twice. Import history into books that start at the boundary.")
        settings = session.get(Settings, 1)
        if settings.lock_date is not None:
            raise LedgerError("A lock date is set; history cannot be posted under it. Clear it first; the import "
                              "sets it to the day before the boundary when done.")

        accounts = session.scalars(select(Account)).all()
        lookup = _resolver(accounts)
        taken = {a.number for a in accounts}
        for name in p.deleted_accounts:
            lookup[name] = _place_deleted(session, name, taken).id

        payees = {_key(pe.name): pe for pe in session.scalars(select(Payee))}
        created_payees = 0
        for t in p.importing:
            if t.name and _key(t.name) not in payees:
                pe = Payee(name=" ".join(t.name.split())[:120], is_vendor=False, is_customer=False,
                           is_active=False, last_used_on=t.when)
                session.add(pe)
                session.flush()
                payees[_key(t.name)] = pe
                created_payees += 1
        invoices = {inv.number: inv for inv in session.scalars(select(Invoice).where(Invoice.source == "QBO"))}

        # Straight inserts rather than post_entry(): post_entry refuses inactive accounts,
        # and history legitimately posts to accounts QuickBooks later deleted. Every rule
        # that matters is still checked -- each transaction balances and has no 0.00 line
        # (parse), every account resolves (above), headers never take postings (_resolver)
        # -- and the database triggers still refuse zero lines and locked dates.
        linked = 0
        for n, t in enumerate(p.importing, start=1):
            description = next((l.description for l in t.lines if l.description), "")
            memo = " ".join(x for x in (f"QBO {t.kind}", f"#{t.number}" if t.number else "", description) if x)
            entry = JournalEntry(entry_date=t.when, memo=memo[:MEMO_MAX], source="IMPORT",
                                 payee_id=payees[_key(t.name)].id if t.name else None,
                                 created_at=audit.utcnow())
            session.add(entry)
            session.flush()
            session.add_all([JournalLine(entry_id=entry.id, line_no=i, account_id=lookup[l.account],
                                         amount=l.amount, memo=l.description[:MEMO_MAX] or None)
                             for i, l in enumerate(t.lines, start=1)])
            if t.kind == "Invoice" and t.number in invoices:
                invoices[t.number].entry_id = entry.id
                linked += 1
            if n % 500 == 0:
                session.flush()

        # Lock the imported years: QuickBooks' history is not edited here.
        settings.lock_date = before - timedelta(days=1)
        s = summary(p, before)
        s["payees_created"] = created_payees
        s["invoices_linked"] = linked
        s["lock_date"] = settings.lock_date.isoformat()
        audit.record(session, "journal.import_qbo", "journal_entry", None,
                     {k: s[k] for k in ("before", "transactions", "lines", "invoices_linked", "lock_date")})
        audit.record(session, "lock_date.move", "settings", 1,
                     {"old": None, "new": s["lock_date"], "backwards": False, "reason": "QuickBooks history imported"})
        return s

""" EOF - qbo_journal.py """
