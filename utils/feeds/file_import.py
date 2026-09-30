"""
General Ledger v0.3.0
File: utils/feeds/file_import.py
Description: Chase CSV import (docs/DESIGN.md section 5.5): parse, preview, then write
             bank_txn rows. Re-importing the same file, or an overlapping one, adds
             nothing that is already there.

Layouts confirmed against real downloads on 2026-09-30:

  card      Transaction Date,Post Date,Description,Category,Type,Amount,Memo
  checking  Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #
            (every data row carries one extra, empty trailing field)

CSV only, by the owner's decision: the QFX export truncates descriptions to 25-32
characters, and its checking FITID is just the date plus a sequence digit -- no more
stable than the content hash below.
"""

import csv
import hashlib
import io
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select

from db import SessionLocal
from models import BankAccount, BankTxn
from utils import audit, suggest
from utils.errors import LedgerError, NotFound
from utils.money import ZERO, parse_amount, to_str

MAX_FILE_BYTES = 5 * 1024 * 1024
PREVIEW_ROWS = 25
DESCRIPTION_MAX = 255

LAYOUTS = {
    "CHASE_CARD": {
        "header": ["Transaction Date", "Post Date", "Description", "Category", "Type", "Amount", "Memo"],
        "kind": "CREDIT",
        # Post Date, not Transaction Date: it is the date on the statement, which is
        # what reconciliation compares against.
        "date": "Post Date",
        "label": "Chase credit card CSV",
    },
    "CHASE_CHECKING": {
        "header": ["Details", "Posting Date", "Description", "Amount", "Type", "Balance", "Check or Slip #"],
        "kind": "DEPOSITORY",
        "date": "Posting Date",
        "label": "Chase checking CSV",
    },
}


def normalise(layout: str, amount: Decimal) -> Decimal:
    """Provider sign -> GL sign for the bank's own account. The ONLY place this happens.

    DESIGN.md section 5.4, confirmed against real files: in both Chase CSV layouts a
    negative amount is money out of checking or a charge on the card, and a positive
    one is a deposit or a card payment/refund. That is already GL sign -- money out
    credits the checking asset; a charge credits the card liability -- so both pass
    through unchanged. The function exists so a future layout with the opposite
    convention has exactly one place to say so.
    """
    if layout in ("CHASE_CARD", "CHASE_CHECKING"):
        return amount
    raise LedgerError(f"No sign rule for layout {layout}.")


@dataclass
class ParsedRow:
    row_no: int
    posted_date: date
    amount: Decimal
    raw_description: str
    description: str
    provider_category: str | None
    balance: Decimal | None
    raw: dict
    external_id: str = ""


@dataclass
class ParsedFile:
    layout: str
    rows: list[ParsedRow] = field(default_factory=list)


def _detect(header: list[str]) -> str:
    cleaned = [h.strip() for h in header]
    for name, spec in LAYOUTS.items():
        if cleaned == spec["header"]:
            return name
    expected = "; ".join(f"{s['label']}: {','.join(s['header'])}" for s in LAYOUTS.values())
    raise LedgerError(f"This is not a Chase CSV this importer knows. Expected one of -- {expected}")


def _collapse(text: str) -> str:
    """Chase pads ACH descriptions with runs of spaces to 300+ characters. Collapsing
    them is display, not editing: the raw text is kept in raw_json and in the hash."""
    return " ".join(text.split())


def parse(content: str) -> ParsedFile:
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise LedgerError("The file is larger than 5 MB; download a shorter date range.")
    reader = csv.reader(io.StringIO(content.lstrip("﻿")))
    try:
        header = next(reader)
    except StopIteration:
        raise LedgerError("The file is empty.") from None
    layout = _detect(header)
    spec = LAYOUTS[layout]
    names = spec["header"]

    parsed = ParsedFile(layout=layout)
    problems = []
    for row_no, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        if len(row) == len(names) + 1 and row[-1] == "":
            row = row[:-1]
        if len(row) != len(names):
            problems.append(f"Row {row_no} has {len(row)} fields, expected {len(names)}.")
            continue
        raw = dict(zip(names, row))
        try:
            posted = datetime.strptime(raw[spec["date"]].strip(), "%m/%d/%Y").date()
            amount = normalise(layout, parse_amount(raw["Amount"], f"Row {row_no} amount"))
            balance = (parse_amount(raw["Balance"], f"Row {row_no} balance")
                       if layout == "CHASE_CHECKING" and raw["Balance"].strip() else None)
        except (ValueError, LedgerError) as e:
            problems.append(str(e) if isinstance(e, LedgerError) else f"Row {row_no} has a bad date.")
            continue
        if amount == 0:
            problems.append(f"Row {row_no} has a zero amount.")
            continue
        category = (raw.get("Category") or "").strip() or raw["Type"].strip() or None
        parsed.rows.append(ParsedRow(
            row_no=row_no, posted_date=posted, amount=amount,
            raw_description=raw["Description"],
            description=_collapse(raw["Description"])[:DESCRIPTION_MAX] or "(no description)",
            provider_category=category, balance=balance, raw=raw,
        ))
    if problems:
        shown = problems[:10] + ([f"...and {len(problems) - 10} more."] if len(problems) > 10 else [])
        raise LedgerError("The file has rows that cannot be read: " + " ".join(shown))
    if not parsed.rows:
        raise LedgerError("The file has no transactions.")
    return parsed


def assign_ids(bank_account_id: int, rows: list[ParsedRow]) -> None:
    """DESIGN.md 5.5: sha256(account | date | amount | description | n).

    n is the occurrence of that exact tuple within the file, so two genuine $5.00
    coffees on the same day stay two rows, while the same file imported twice -- or two
    downloads that overlap -- produce the same ids and add nothing. Chase dates are whole
    days, so an overlapping download always contains a shared day in full.
    """
    seen: Counter = Counter()
    for row in rows:
        key = (row.posted_date.isoformat(), str(row.amount), row.raw_description)
        seen[key] += 1
        material = "|".join((str(bank_account_id), *key, str(seen[key])))
        row.external_id = hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass
class Plan:
    """What an import would do. Preview shows it; import carries it out."""

    account: BankAccount
    parsed: ParsedFile
    new: list[ParsedRow]
    before_start: int
    already_present: int
    overlaps_feed: int


def _plan(session, bank_account_id: int, content: str) -> Plan:
    account = session.get(BankAccount, bank_account_id)
    if account is None:
        raise NotFound(f"Bank account {bank_account_id} does not exist.")
    parsed = parse(content)
    spec = LAYOUTS[parsed.layout]
    if spec["kind"] != account.kind:
        raise LedgerError(
            f"This file is a {spec['label']}, but {account.name} is a "
            f"{'credit card' if account.kind == 'CREDIT' else 'checking'} account."
        )
    assign_ids(account.id, parsed.rows)

    in_range = [r for r in parsed.rows if r.posted_date >= account.feed_start_date]
    before_start = len(parsed.rows) - len(in_range)

    existing = set()
    if in_range:
        existing = set(session.scalars(
            select(BankTxn.external_id).where(
                BankTxn.bank_account_id == account.id, BankTxn.source == "FILE",
                BankTxn.external_id.in_([r.external_id for r in in_range]),
            )
        ))
    candidates = [r for r in in_range if r.external_id not in existing]

    # A file overlapping dates a live feed already covers would double-count: the two
    # sources give the same line different ids (DESIGN.md section 5.5).
    feed_dates = set(session.scalars(
        select(BankTxn.posted_date).where(BankTxn.bank_account_id == account.id,
                                          BankTxn.source != "FILE").distinct()
    ))
    new = [r for r in candidates if r.posted_date not in feed_dates]
    return Plan(account=account, parsed=parsed, new=new, before_start=before_start,
                already_present=len(in_range) - len(candidates),
                overlaps_feed=len(candidates) - len(new))


def _summary(plan: Plan) -> dict:
    dates = [r.posted_date for r in plan.parsed.rows]
    new_sum = sum((r.amount for r in plan.new), ZERO)
    return {
        "layout": LAYOUTS[plan.parsed.layout]["label"],
        "bank_account": {"id": plan.account.id, "name": plan.account.name},
        "feed_start_date": plan.account.feed_start_date.isoformat(),
        "rows_in_file": len(plan.parsed.rows),
        "first_date": min(dates).isoformat(),
        "last_date": max(dates).isoformat(),
        "before_start": plan.before_start,
        "already_present": plan.already_present,
        "overlaps_feed": plan.overlaps_feed,
        "new": len(plan.new),
        "new_total": to_str(new_sum),
        "sample": [
            {"posted_date": r.posted_date.isoformat(), "description": r.description,
             "amount": to_str(r.amount), "category": r.provider_category}
            for r in sorted(plan.new, key=lambda r: (r.posted_date, r.row_no), reverse=True)[:PREVIEW_ROWS]
        ],
    }


def preview(bank_account_id: int, content: str) -> dict:
    with SessionLocal() as session:
        return _summary(_plan(session, bank_account_id, content))


def import_file(bank_account_id: int, content: str, filename: str | None) -> dict:
    filename = (filename or "").strip()[:200] or None
    with SessionLocal.begin() as session:
        plan = _plan(session, bank_account_id, content)
        now = audit.utcnow()
        for r in plan.new:
            session.add(BankTxn(
                bank_account_id=plan.account.id, source="FILE", external_id=r.external_id,
                posted_date=r.posted_date, amount=r.amount, description=r.description,
                merchant_name=None, provider_category=(r.provider_category or "")[:120] or None,
                status="NEW",
                raw_json={"file": filename, "row": r.row_no, "layout": plan.parsed.layout, "fields": r.raw},
                first_seen_at=now,
            ))

        # Checking carries a running balance. The newest row's balance is what the bank
        # last reported, and it only ever moves forward: importing an older file after a
        # newer one must not wind it back.
        with_balance = [r for r in plan.parsed.rows if r.balance is not None]
        if with_balance:
            newest = max(r.posted_date for r in with_balance)
            latest = next(r for r in with_balance if r.posted_date == newest)  # Chase lists newest first
            as_of = datetime(newest.year, newest.month, newest.day)
            if plan.account.reported_balance_at is None or plan.account.reported_balance_at <= as_of:
                plan.account.reported_balance = latest.balance
                plan.account.reported_balance_at = as_of

        session.flush()
        # New lines arrive with their suggestions (and card payments paired) already made.
        summary = _summary(plan)
        summary["suggestions"] = suggest.run(session)
        audit.record(session, "bank.import", "bank_account", plan.account.id, {
            "file": filename, "layout": plan.parsed.layout, "rows": len(plan.parsed.rows),
            "added": len(plan.new), "already_present": plan.already_present,
            "before_start": plan.before_start, "overlaps_feed": plan.overlaps_feed,
        })
        session.flush()
        return summary


def last_import(session, bank_account_id: int) -> datetime | None:
    return session.scalar(select(func.max(BankTxn.first_seen_at)).where(
        BankTxn.bank_account_id == bank_account_id, BankTxn.source == "FILE"))

""" EOF - file_import.py """
