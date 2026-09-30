"""
General Ledger v0.3.1
File: utils/migration/qbo_chart.py
Description: Replace the chart of accounts with QuickBooks Online's "Account List"
             report (CSV export). Part of docs/DESIGN.md section 10, brought forward so
             the review queue is exercised against the real chart.

Decisions confirmed by the owner on 2026-09-30:
  - every account comes across, dead ones included (deactivate them afterwards);
  - QBO has no account numbers here, so they are assigned by type, alphabetically;
  - a parent with sub-accounts cannot take postings in this ledger, so each parent gets
    a "<Parent> - General" sub-account for what QBO posted to the parent itself;
  - balances are NOT imported: opening balances are one entry at cutover (phase 3).

Only runs against empty books: replacing accounts under existing postings would
silently re-point history.
"""

import csv
import io
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select, update

from db import SessionLocal
from models import Account, BankAccount, BankConnection, BankTxn, JournalLine, Payee, Settings
from utils import audit
from utils.errors import LedgerError

HEADER = ["Account Name", "Type", "Detail type", "Description", "Total balance"]
GENERAL_SUFFIX = " - General"

# QBO type -> (ledger type, first number, last number, feed-capable)
TYPE_BLOCKS = {
    "Bank": ("ASSET", 1010, 1099, True),
    "Accounts receivable (A/R)": ("ASSET", 1200, 1299, False),
    "Other Current Assets": ("ASSET", 1300, 1499, False),
    "Fixed Assets": ("ASSET", 1500, 1799, False),
    "Other Assets": ("ASSET", 1800, 1999, False),
    "Accounts payable (A/P)": ("LIABILITY", 2000, 2099, False),
    "Credit Card": ("LIABILITY", 2100, 2199, True),
    "Other Current Liabilities": ("LIABILITY", 2200, 2499, False),
    "Long Term Liabilities": ("LIABILITY", 2500, 2999, False),
    "Equity": ("EQUITY", 3000, 3899, False),
    "Income": ("INCOME", 4000, 4899, False),
    "Other Income": ("INCOME", 4900, 4999, False),
    "Cost of Goods Sold": ("EXPENSE", 5000, 5999, False),
    "Expenses": ("EXPENSE", 6000, 6999, False),
    "Other Expense": ("EXPENSE", 7000, 7999, False),
}
RETAINED_EARNINGS_NUMBER = 3900


@dataclass
class QboAccount:
    full_name: str          # "Web Services:Internet", as QBO writes it
    name: str               # "Internet"
    parent: str | None      # "Web Services"
    qbo_type: str
    detail_type: str
    description: str | None


@dataclass
class Planned:
    number: str
    name: str
    type: str
    parent_number: str | None
    qbo_name: str | None    # None for a synthesised "- General" account
    qbo_type: str
    is_bank_account: bool
    description: str | None
    children: list = field(default_factory=list)


def parse(content: str) -> list[QboAccount]:
    rows = list(csv.reader(io.StringIO(content.lstrip("﻿"))))
    try:
        start = next(i for i, r in enumerate(rows) if [c.strip() for c in r[:5]] == HEADER)
    except StopIteration:
        raise LedgerError("This is not a QuickBooks Online Account List export "
                          f"(no header row {','.join(HEADER)}).") from None
    accounts = []
    for r in rows[start + 1:]:
        if not r or not r[0].strip() or r[0].strip() == "TOTAL" or len(r) < 2 or not r[1].strip():
            continue  # blanks, the TOTAL line, and the timestamp footer
        full = r[0].strip()
        if full.count(":") > 1:
            raise LedgerError(f"{full} is nested more than one level; flatten it in QuickBooks first.")
        parent, _, name = full.rpartition(":")
        qbo_type = r[1].strip()
        if qbo_type not in TYPE_BLOCKS:
            raise LedgerError(f"{full} has QuickBooks type {qbo_type!r}, which this importer does not map.")
        accounts.append(QboAccount(full_name=full, name=name.strip(), parent=parent.strip() or None,
                                   qbo_type=qbo_type, detail_type=r[2].strip(),
                                   description=(r[3].strip() or None) if len(r) > 3 else None))
    if not accounts:
        raise LedgerError("The Account List has no accounts.")
    names = {a.full_name for a in accounts}
    for a in accounts:
        if a.parent and a.parent not in names:
            raise LedgerError(f"{a.full_name}'s parent {a.parent} is not in the list.")
    return accounts


def plan(accounts: list[QboAccount]) -> list[Planned]:
    """Numbers by type block, alphabetical; a parent's sub-accounts follow it as +1, +2...

    The next top-level account starts at the next multiple of ten after the last
    sub-account, so a parent with ten sub-accounts simply takes a wider slot.
    """
    by_parent: dict[str, list[QboAccount]] = {}
    for a in accounts:
        if a.parent:
            by_parent.setdefault(a.parent, []).append(a)

    planned: list[Planned] = []
    for qbo_type, (ledger_type, first, last, feed_capable) in TYPE_BLOCKS.items():
        tops = sorted((a for a in accounts if a.qbo_type == qbo_type and not a.parent),
                      key=lambda a: a.name.lower())
        n = first
        for top in tops:
            is_re = qbo_type == "Equity" and top.detail_type == "Retained Earnings"
            number = RETAINED_EARNINGS_NUMBER if is_re else n
            parent = Planned(str(number), top.name, ledger_type, None, top.full_name, qbo_type,
                             feed_capable, top.description)
            planned.append(parent)
            kids = sorted(by_parent.get(top.full_name, []), key=lambda a: a.name.lower())
            child_no = number
            if kids:
                child_no += 1
                planned.append(Planned(str(child_no), top.name + GENERAL_SUFFIX, ledger_type, parent.number,
                                       None, qbo_type, False,
                                       f"What QuickBooks posted to {top.name} itself"))
                for kid in kids:
                    child_no += 1
                    planned.append(Planned(str(child_no), kid.name, ledger_type, parent.number,
                                           kid.full_name, kid.qbo_type, feed_capable, kid.description))
            if is_re:
                continue  # its fixed slot sits outside the running sequence
            if child_no > last:
                raise LedgerError(f"QuickBooks type {qbo_type} has too many accounts for {first}-{last}.")
            n = (child_no // 10 + 1) * 10
    numbers = [p.number for p in planned]
    if len(numbers) != len(set(numbers)):
        raise LedgerError("Numbering produced a duplicate; the Retained Earnings slot collided.")
    return planned


def preview(content: str) -> dict:
    accounts = parse(content)
    planned = plan(accounts)
    return {
        "qbo_accounts": len(accounts),
        "ledger_accounts": len(planned),
        "general_subaccounts": sum(1 for p in planned if p.qbo_name is None),
        "accounts": [
            {"number": p.number, "name": p.name, "type": p.type, "parent": p.parent_number,
             "qbo_name": p.qbo_name, "qbo_type": p.qbo_type, "bank": p.is_bank_account}
            for p in sorted(planned, key=lambda p: int(p.number))
        ],
    }


def apply(content: str) -> dict:
    accounts = parse(content)
    planned = plan(accounts)
    ar = [p for p in planned if p.qbo_type == "Accounts receivable (A/R)" and p.parent_number is None]
    re_ = [p for p in planned if p.number == str(RETAINED_EARNINGS_NUMBER)]
    if len(ar) != 1 or len(re_) != 1:
        raise LedgerError("The chart needs exactly one Accounts Receivable and one Retained Earnings account.")

    with SessionLocal.begin() as session:
        if session.scalar(select(func.count()).select_from(JournalLine)) or \
                session.scalar(select(func.count()).select_from(BankTxn)):
            raise LedgerError("The books are not empty. The chart can only be replaced before anything is posted.")

        old_ids = list(session.scalars(select(Account.id)))
        # New accounts go in under temporary numbers first: the old chart still holds
        # the real ones, and settings must point at the new AR and RE accounts before
        # the old ones can be deleted.
        ids: dict[str, int] = {}
        for p in sorted(planned, key=lambda p: p.parent_number is not None):
            account = Account(number=f"N{p.number}", name=p.name[:100], type=p.type,
                              parent_id=ids.get(p.parent_number), is_active=True,
                              is_bank_account=p.is_bank_account,
                              description=(p.description or None) and p.description[:255])
            session.add(account)
            session.flush()
            ids[p.number] = account.id

        session.execute(update(Settings).where(Settings.id == 1).values(
            ar_account_id=ids[ar[0].number], retained_earnings_account_id=ids[re_[0].number]))
        session.execute(update(Payee).values(default_account_id=None))
        session.execute(delete(BankAccount))
        session.execute(delete(BankConnection).where(BankConnection.provider == "FILE"))
        if old_ids:
            session.execute(update(Account).where(Account.id.in_(old_ids)).values(parent_id=None))
            session.execute(delete(Account).where(Account.id.in_(old_ids)))
        for number, account_id in ids.items():
            session.execute(update(Account).where(Account.id == account_id).values(number=number))

        audit.record(session, "chart.import_qbo", "account", None, {
            "qbo_accounts": len(accounts), "ledger_accounts": len(planned), "replaced": len(old_ids)})
    return {"imported": len(planned), "replaced": len(old_ids)}

""" EOF - qbo_chart.py """
