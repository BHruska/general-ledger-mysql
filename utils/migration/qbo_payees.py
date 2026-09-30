"""
General Ledger v0.3.3
File: utils/migration/qbo_payees.py
Description: Payees from QuickBooks Online: the "Vendor Contact List" export plus every
             name in "Transaction Detail by Account" (All Dates). Part of docs/DESIGN.md
             section 10.

Decisions confirmed by the owner on 2026-09-30:
  - everyone comes across, so the ledger matches QuickBooks history;
  - payees used since --active-since (default 2024-01-01) are active, the rest are kept
    but archived (is_active = FALSE) so they stay out of pickers and suggestions;
  - last_used_on comes from the history, and a default account only where history is
    consistent: the same account on at least 75% of the payee's bank and card lines
    since --active-since (all history only for payees with nothing that recent).

Needs the chart already imported (qbo_chart.py): defaults are resolved against it.
"""

import csv
import io
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select

from db import SessionLocal
from models import Account, BankTxn, JournalEntry, Payee
from utils import audit
from utils.errors import LedgerError

VENDOR_HEADER = ["Vendor", "Company", "Phone numbers", "Email", "Full name", "Billing address",
                 "Account #", "Tax ID", "Track 1099"]
TXN_HEADER = ["", "Transaction date", "Transaction type", "Num", "Name", "Description", "Split",
              "Amount", "Balance"]
CUSTOMER_TYPES = {"Invoice", "Payment", "Sales Receipt", "Credit Memo", "Refund"}
# Decided by transaction type, not amount sign: QBO writes a card charge as a positive
# amount in the card's section, so "money out" by sign misses every card vendor.
VENDOR_TYPES = {"Expense", "Check", "Bill", "Bill Payment (Check)", "Bill Payment (Credit Card)",
                "Credit Card Credit", "Vendor Credit", "Purchase Order"}
DEFAULT_SHARE = Decimal("0.75")
NAME_MAX = 120


@dataclass
class PayeeStats:
    name: str
    in_vendor_list: bool = False
    address: str | None = None
    is_1099: bool = False
    lines: int = 0
    last_used: date | None = None
    customer: bool = False
    vendor_lines: int = 0
    splits: Counter = field(default_factory=Counter)          # offset account on bank/card lines
    recent_splits: Counter = field(default_factory=Counter)   # the same, since active_since


def _key(name: str) -> str:
    """The database compares names case-insensitively and ignores trailing spaces
    (utf8mb4_unicode_ci), so "Amazon" and "AMAZON" are one payee here too."""
    return " ".join(name.split()).casefold()


def _find_header(rows: list[list[str]], header: list[str], what: str) -> int:
    for i, r in enumerate(rows):
        if [c.strip() for c in r[:len(header)]] == header:
            return i
    raise LedgerError(f"This is not a QuickBooks Online {what} export (no header {','.join(h for h in header if h)}).")


def _bank_sections(chart_rows: list[Account]) -> set[str]:
    return {a.name for a in chart_rows if a.is_bank_account}


def parse(vendor_csv: str, txn_csv: str, bank_accounts: set[str],
          active_since: date) -> dict[str, PayeeStats]:
    stats: dict[str, PayeeStats] = {}

    def get(name: str) -> PayeeStats:
        k = _key(name)
        if k not in stats:
            stats[k] = PayeeStats(name=" ".join(name.split())[:NAME_MAX])
        return stats[k]

    rows = list(csv.reader(io.StringIO(vendor_csv.lstrip("﻿"))))
    start = _find_header(rows, VENDOR_HEADER, "Vendor Contact List")
    for r in rows[start + 1:]:
        # Every real vendor row says Yes or No under Track 1099. The report's timestamp
        # footer (" Wednesday, September 30, ...") has the same field count and would
        # otherwise become a payee.
        if len(r) < len(VENDOR_HEADER) or not r[0].strip() or r[8].strip() not in ("Yes", "No"):
            continue
        p = get(r[0])
        p.in_vendor_list = True
        p.address = r[5].strip() or p.address
        p.is_1099 = p.is_1099 or r[8].strip() == "Yes"

    rows = list(csv.reader(io.StringIO(txn_csv.lstrip("﻿"))))
    start = _find_header(rows, TXN_HEADER, "Transaction Detail by Account")
    section = None
    for r in rows[start + 1:]:
        if not r or not any(c.strip() for c in r):
            continue
        if r[0].strip():
            # "HGRP Visa" opens a section; "Total for HGRP Visa" and the footer close one.
            section = None if r[0].startswith("Total for") or any(c.strip() for c in r[1:]) else r[0].strip()
            continue
        name = r[4].strip() if len(r) > 4 else ""
        if not name or not r[1].strip():
            continue
        try:
            when = datetime.strptime(r[1].strip(), "%m/%d/%Y").date()
        except ValueError:
            continue
        p = get(name)
        p.lines += 1
        p.last_used = max(p.last_used or when, when)
        kind = r[2].strip()
        if kind in CUSTOMER_TYPES:
            p.customer = True
        if kind in VENDOR_TYPES:
            p.vendor_lines += 1
        # A bank or card line's Split is where the money went: the evidence for a
        # default account. Deleted QBO accounts are all old banks and cards.
        if section and (section in bank_accounts or section.endswith("(deleted)")):
            split = r[6].strip()
            if split and split != "-Split-":
                p.splits[split] += 1
                if when >= active_since:
                    p.recent_splits[split] += 1
    return stats


def _account_lookup(accounts: list[Account]) -> dict[str, int]:
    """QBO full name -> ledger account id, as qbo_chart.py laid the chart out.

    A parent with sub-accounts resolves to its "- General" sub-account, because a
    header takes no postings here; bank and card accounts resolve to nothing, because
    a transfer is not a default for a payee.
    """
    by_id = {a.id: a for a in accounts}
    lookup: dict[str, int] = {}
    generals = {a.parent_id: a.id for a in accounts if a.parent_id and a.name.endswith(" - General")}
    headers = {a.parent_id for a in accounts if a.parent_id}
    for a in accounts:
        if a.is_bank_account:
            continue
        if a.parent_id is None:
            # A header with no "- General" sub-account has nowhere to post: no default.
            target = generals.get(a.id) if a.id in headers else a.id
            if target is not None:
                lookup[a.name] = target
        elif not a.name.endswith(" - General"):
            lookup[f"{by_id[a.parent_id].name}:{a.name}"] = a.id
    return lookup


@dataclass
class PlannedPayee:
    name: str
    is_vendor: bool
    is_customer: bool
    is_active: bool
    is_1099: bool
    last_used: date | None
    lines: int
    default_account_id: int | None
    default_account: str | None
    address: str | None


def plan(vendor_csv: str, txn_csv: str, active_since: date) -> tuple[list[PlannedPayee], dict]:
    with SessionLocal() as session:
        accounts = session.scalars(select(Account)).all()
    stats = parse(vendor_csv, txn_csv, _bank_sections(accounts), active_since)
    lookup = _account_lookup(accounts)
    labels = {a.id: f"{a.number} {a.name}" for a in accounts}

    planned, unmapped = [], Counter()
    for p in sorted(stats.values(), key=lambda s: s.name.casefold()):
        default_id = None
        # Current practice decides: how a vendor was categorised in 2014 says little
        # about today. Only a payee with no recent lines falls back to all its history.
        evidence = p.recent_splits or p.splits
        total = sum(evidence.values())
        if total:
            top, n = evidence.most_common(1)[0]
            if Decimal(n) / total >= DEFAULT_SHARE:
                default_id = lookup.get(top)
                if default_id is None and top not in {a.name for a in accounts if a.is_bank_account}:
                    unmapped[top] += 1
        planned.append(PlannedPayee(
            name=p.name,
            is_vendor=p.in_vendor_list or p.vendor_lines > 0,
            is_customer=p.customer,
            is_active=p.last_used is not None and p.last_used >= active_since,
            is_1099=p.is_1099,
            last_used=p.last_used,
            lines=p.lines,
            default_account_id=default_id,
            default_account=labels.get(default_id),
            address=p.address,
        ))
    summary = {
        "payees": len(planned),
        "active": sum(1 for p in planned if p.is_active),
        "archived": sum(1 for p in planned if not p.is_active),
        "never_used": sum(1 for p in planned if p.last_used is None),
        "with_default_account": sum(1 for p in planned if p.default_account_id),
        "vendors": sum(1 for p in planned if p.is_vendor),
        "customers": sum(1 for p in planned if p.is_customer),
        "active_since": active_since.isoformat(),
        # A consistent history pointing at an account no longer in the chart (a deleted
        # QBO account): those payees simply get no default.
        "unmapped_defaults": dict(unmapped.most_common()),
    }
    return planned, summary


def apply(vendor_csv: str, txn_csv: str, active_since: date, replace: bool = False) -> dict:
    planned, summary = plan(vendor_csv, txn_csv, active_since)
    with SessionLocal.begin() as session:
        existing = session.scalar(select(func.count()).select_from(Payee))
        if existing and not replace:
            raise LedgerError(f"{existing} payees already exist. Re-run with --replace to start over.")
        if existing:
            referenced = (session.scalar(select(func.count()).select_from(JournalEntry)
                                         .where(JournalEntry.payee_id.isnot(None)))
                          or session.scalar(select(func.count()).select_from(BankTxn)
                                            .where(BankTxn.suggested_payee_id.isnot(None))))
            if referenced:
                raise LedgerError("Existing payees are already used by postings or suggestions; "
                                  "they cannot be replaced.")
            session.query(Payee).delete()
        for p in planned:
            session.add(Payee(name=p.name, is_vendor=p.is_vendor, is_customer=p.is_customer,
                              address=p.address, default_account_id=p.default_account_id,
                              is_1099_vendor=p.is_1099, is_active=p.is_active,
                              last_used_on=p.last_used))
        audit.record(session, "payees.import_qbo", "payee", None,
                     {k: v for k, v in summary.items() if k != "unmapped_defaults"})
    return summary

""" EOF - qbo_payees.py """
