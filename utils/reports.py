"""
General Ledger v0.2.0
File: utils/reports.py
Description: Reports computed on the server (docs/DESIGN.md section 9); the page only
             formats. Phase 1: trial balance and account register.

Retained earnings are computed, not posted (section 3.4): at date D, income and expense
before the start of D's fiscal year are folded into the Retained Earnings account, and
income and expense accounts show only the current fiscal year. No closing entry exists,
so nothing needs re-running when a prior-year entry changes.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from db import SessionLocal
from models import NORMAL_SIGN, Account, JournalEntry, JournalLine, Settings
from utils.errors import LedgerError, NotFound
from utils.money import ZERO, to_str

PNL_TYPES = ("INCOME", "EXPENSE")


def fiscal_year_start(d: date, start_month: int) -> date:
    year = d.year if d.month >= start_month else d.year - 1
    return date(year, start_month, 1)


def _sums(session, where) -> dict[int, Decimal]:
    rows = session.execute(
        select(JournalLine.account_id, func.sum(JournalLine.amount))
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(*where)
        .group_by(JournalLine.account_id)
    ).all()
    return {account_id: total for account_id, total in rows}


def trial_balance(as_of: date) -> dict:
    """Every account's balance at `as_of`, as a debit or a credit. Totals must agree."""
    with SessionLocal() as session:
        settings = session.get(Settings, 1)
        fy_start = fiscal_year_start(as_of, settings.fiscal_year_start_month)
        accounts = session.scalars(select(Account).order_by(Account.number)).all()
        by_id = {a.id: a for a in accounts}
        pnl_ids = {a.id for a in accounts if a.type in PNL_TYPES}

        to_date = _sums(session, [JournalEntry.entry_date <= as_of])
        before_fy = _sums(session, [JournalEntry.entry_date < fy_start])

        balances: dict[int, Decimal] = {}
        prior_net = ZERO  # signed: debit positive, so a profit is negative here
        for account_id, total in to_date.items():
            if account_id in pnl_ids:
                earlier = before_fy.get(account_id, ZERO)
                prior_net += earlier
                balances[account_id] = total - earlier
            else:
                balances[account_id] = total
        re_id = settings.retained_earnings_account_id
        balances[re_id] = balances.get(re_id, ZERO) + prior_net

        rollup: dict[int, Decimal] = {}
        for account_id, amount in balances.items():
            parent = by_id[account_id].parent_id
            if parent is not None:
                rollup[parent] = rollup.get(parent, ZERO) + amount
        headers = {a.parent_id for a in accounts if a.parent_id is not None}

        rows, total_debit, total_credit = [], ZERO, ZERO
        for a in accounts:
            is_header = a.id in headers
            amount = rollup.get(a.id, ZERO) if is_header else balances.get(a.id, ZERO)
            if amount == 0 and not (is_header and a.id in rollup):
                continue
            debit = amount if amount > 0 else None
            credit = -amount if amount < 0 else None
            if not is_header:
                total_debit += debit or ZERO
                total_credit += credit or ZERO
            rows.append({
                "account_id": a.id, "number": a.number, "name": a.name, "type": a.type,
                "parent_id": a.parent_id, "is_header": is_header,
                "debit": to_str(debit), "credit": to_str(credit),
            })

        return {
            "as_of": as_of.isoformat(),
            "fiscal_year_start": fy_start.isoformat(),
            "rows": rows,
            "total_debit": to_str(total_debit),
            "total_credit": to_str(total_credit),
            "balanced": total_debit == total_credit,
            # Shown on the page so the Retained Earnings figure is explainable.
            "prior_years_net_income": to_str(-prior_net),
        }


def account_register(account_id: int, start: date, end: date) -> dict:
    """One account's lines with a running balance in its normal direction."""
    if end < start:
        raise LedgerError("The end date is before the start date.")
    with SessionLocal() as session:
        account = session.get(Account, account_id)
        if account is None:
            raise NotFound(f"Account {account_id} does not exist.")
        sign = NORMAL_SIGN[account.type]

        # A P&L account's balance restarts each fiscal year (section 3.4), so its
        # opening balance counts only this fiscal year's lines before `start`.
        opening_where = [JournalLine.account_id == account_id, JournalEntry.entry_date < start]
        if account.type in PNL_TYPES:
            fy = fiscal_year_start(start, session.get(Settings, 1).fiscal_year_start_month)
            opening_where.append(JournalEntry.entry_date >= fy)
        opening = session.execute(
            select(func.coalesce(func.sum(JournalLine.amount), 0))
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(*opening_where)
        ).scalar_one()

        rows = session.execute(
            select(JournalLine, JournalEntry)
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(JournalLine.account_id == account_id, JournalEntry.entry_date.between(start, end))
            .order_by(JournalEntry.entry_date, JournalEntry.id, JournalLine.line_no)
        ).all()

        # The "other side" of each entry, for a register that reads like a bank statement.
        entry_ids = {entry.id for _line, entry in rows}
        others: dict[int, list[str]] = {}
        if entry_ids:
            names = {a.id: f"{a.number} {a.name}" for a in session.scalars(select(Account))}
            for line in session.scalars(
                select(JournalLine).where(JournalLine.entry_id.in_(entry_ids),
                                          JournalLine.account_id != account_id)
            ):
                others.setdefault(line.entry_id, []).append(names[line.account_id])

        running = opening
        lines = []
        for line, entry in rows:
            running += line.amount
            other = sorted(set(others.get(entry.id, [])))
            lines.append({
                "entry_id": entry.id,
                "entry_date": entry.entry_date.isoformat(),
                "source": entry.source,
                "memo": line.memo or entry.memo,
                "other_side": other[0] if len(other) == 1 else ("Split" if other else None),
                "debit": to_str(line.amount) if line.amount > 0 else None,
                "credit": to_str(-line.amount) if line.amount < 0 else None,
                "balance": to_str(running * sign),
                "cleared": line.cleared_recon_id is not None,
                "reversed": entry.reversed_by_entry_id is not None or entry.reverses_entry_id is not None,
            })

        return {
            "account": {"id": account.id, "number": account.number, "name": account.name,
                        "type": account.type},
            "start": start.isoformat(),
            "end": end.isoformat(),
            "opening_balance": to_str(opening * sign),
            "closing_balance": to_str(running * sign),
            "lines": lines,
        }


def default_range(today: date | None = None) -> tuple[date, date]:
    """This fiscal year to date: the range every date-ranged page opens on."""
    today = today or date.today()
    with SessionLocal() as session:
        month = session.get(Settings, 1).fiscal_year_start_month
    return fiscal_year_start(today, month), today

""" EOF - reports.py """
