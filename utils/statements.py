"""
General Ledger v0.6.0
File: utils/statements.py
Description: Profit & Loss, Balance Sheet and General Ledger detail (docs/DESIGN.md
             section 9), computed on the server; the pages only format.

Both statements follow QuickBooks Online's layout, so they can be compared with it line by
line. The account-number blocks utils/migration/qbo_chart.py assigned carry QuickBooks'
own account types, and that is what the sections below are keyed on; an account numbered
outside every block falls into its type's main section.

Retained earnings are computed, not posted (DESIGN.md 3.4): utils/reports._balances does it
once for every report, so no two can disagree.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from db import SessionLocal
from models import NORMAL_SIGN, Account, BankTxn, JournalEntry, JournalLine, Payee, Settings
from utils.errors import LedgerError, NotFound
from utils.money import ZERO, to_str
from utils.reports import PNL_TYPES, _balances, fiscal_year_start

# (key, label, account type, first number, last number)
PNL_SECTIONS = [
    ("income", "Income", "INCOME", 4000, 4899),
    ("cogs", "Cost of Goods Sold", "EXPENSE", 5000, 5999),
    ("expenses", "Expenses", "EXPENSE", 6000, 6999),
    ("other_income", "Other Income", "INCOME", 4900, 4999),
    ("other_expense", "Other Expenses", "EXPENSE", 7000, 7999),
]
BS_SECTIONS = [
    ("bank", "Bank Accounts", "ASSET", 1000, 1199),
    ("ar", "Accounts Receivable", "ASSET", 1200, 1299),
    ("other_current_assets", "Other Current Assets", "ASSET", 1300, 1499),
    ("fixed_assets", "Fixed Assets", "ASSET", 1500, 1799),
    ("other_assets", "Other Assets", "ASSET", 1800, 1999),
    ("ap", "Accounts Payable", "LIABILITY", 2000, 2099),
    ("credit_cards", "Credit Cards", "LIABILITY", 2100, 2199),
    ("other_current_liabilities", "Other Current Liabilities", "LIABILITY", 2200, 2499),
    ("long_term_liabilities", "Long-Term Liabilities", "LIABILITY", 2500, 2999),
    ("equity", "Equity", "EQUITY", 3000, 3999),
]
FALLBACK_SECTION = {"INCOME": "income", "EXPENSE": "expenses", "ASSET": "other_current_assets",
                    "LIABILITY": "other_current_liabilities", "EQUITY": "equity"}
COMPARISONS = ("none", "prior_period", "prior_year")


def _section_of(account: Account, sections) -> str:
    # A bank or card account is one whatever its number: the flag is the owner's own
    # statement, where a number block is only QuickBooks' convention.
    if account.is_bank_account and sections is BS_SECTIONS:
        if account.type == "ASSET":
            return "bank"
        if account.type == "LIABILITY":
            return "credit_cards"
    try:
        n = int(account.number)
    except ValueError:
        n = -1
    for key, _, type_, lo, hi in sections:
        if account.type == type_ and lo <= n <= hi:
            return key
    return FALLBACK_SECTION[account.type]


def _shift_year(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February
        return d.replace(year=d.year + years, day=28)


def _period_sums(session, start: date, end: date) -> dict[int, Decimal]:
    rows = session.execute(
        select(JournalLine.account_id, func.sum(JournalLine.amount))
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(JournalEntry.entry_date.between(start, end))
        .group_by(JournalLine.account_id)).all()
    return {a: t for a, t in rows}


def _rows(accounts: list[Account], values: list[dict[int, Decimal]], keep) -> list[dict]:
    """Account rows in number order, headers rolled up from their sub-accounts, each value
    already in the account's normal direction. `keep(account)` limits which leaves count."""
    by_id = {a.id: a for a in accounts}
    headers = {a.parent_id for a in accounts if a.parent_id}
    rollups: dict[int, list[Decimal]] = {}
    for a in accounts:
        if a.id in headers or not keep(a):
            continue
        if a.parent_id:
            r = rollups.setdefault(a.parent_id, [ZERO] * len(values))
            for i, v in enumerate(values):
                r[i] += v.get(a.id, ZERO)
    rows = []
    for a in accounts:
        is_header = a.id in headers
        if is_header:
            if a.id not in rollups or not keep(a):
                continue
            amounts = rollups[a.id]
        else:
            if not keep(a):
                continue
            amounts = [v.get(a.id, ZERO) for v in values]
        if not is_header and all(x == 0 for x in amounts):
            continue
        rows.append({"account_id": a.id, "number": a.number, "name": a.name,
                     "depth": 1 if a.parent_id and a.parent_id in by_id else 0,
                     "is_header": is_header, "amounts": amounts})
    # A header whose sub-accounts are all zero leaves nothing to show under it.
    shown_parents = {by_id[r["account_id"]].parent_id for r in rows if not r["is_header"]}
    return [r for r in rows if not r["is_header"] or r["account_id"] in shown_parents]


def _columns_json(rows):
    for r in rows:
        r["amounts"] = [to_str(x) for x in r["amounts"]]
    return rows


# ---------------------------------------------------------------- Profit & Loss

def profit_and_loss(start: date, end: date, compare: str = "none") -> dict:
    if end < start:
        raise LedgerError("The end date is before the start date.")
    if compare not in COMPARISONS:
        raise LedgerError(f"Unknown comparison {compare!r}.")
    periods = [(start, end)]
    if compare == "prior_period":
        length = end - start
        periods.append((start - length - timedelta(days=1), start - timedelta(days=1)))
    elif compare == "prior_year":
        periods.append((_shift_year(start, -1), _shift_year(end, -1)))

    with SessionLocal() as session:
        accounts = session.scalars(select(Account).where(Account.type.in_(PNL_TYPES))
                                   .order_by(Account.number)).all()
        values = []
        for s, e in periods:
            sums = _period_sums(session, s, e)
            values.append({a.id: sums.get(a.id, ZERO) * NORMAL_SIGN[a.type] for a in accounts})

    sections, totals = [], {}
    for key, label, _, _, _ in PNL_SECTIONS:
        rows = _rows(accounts, values, lambda a, k=key: _section_of(a, PNL_SECTIONS) == k)
        total = [sum((r["amounts"][i] for r in rows if not r["is_header"]), ZERO) for i in range(len(periods))]
        totals[key] = total
        sections.append({"key": key, "label": label, "rows": _columns_json(rows),
                         "total": [to_str(x) for x in total]})

    def combine(f):
        return [f(i) for i in range(len(periods))]

    gross = combine(lambda i: totals["income"][i] - totals["cogs"][i])
    operating = combine(lambda i: gross[i] - totals["expenses"][i])
    other = combine(lambda i: totals["other_income"][i] - totals["other_expense"][i])
    net = combine(lambda i: operating[i] + other[i])
    return {
        "start": start.isoformat(), "end": end.isoformat(), "compare": compare,
        "columns": [{"start": s.isoformat(), "end": e.isoformat()} for s, e in periods],
        "sections": sections,
        "gross_profit": [to_str(x) for x in gross],
        "net_operating_income": [to_str(x) for x in operating],
        "net_other_income": [to_str(x) for x in other],
        "net_income": [to_str(x) for x in net],
    }


# ---------------------------------------------------------------- Balance Sheet

def balance_sheet(as_of: date, compare: str = "none") -> dict:
    if compare not in ("none", "prior_year"):
        raise LedgerError("A balance sheet compares with the prior year or nothing.")
    dates = [as_of] + ([_shift_year(as_of, -1)] if compare == "prior_year" else [])
    with SessionLocal() as session:
        snapshots = [_balances(session, d) for d in dates]
    accounts = [a for a in snapshots[0].accounts if a.type not in PNL_TYPES]
    values = [{a.id: b.balances.get(a.id, ZERO) * NORMAL_SIGN[a.type] for a in accounts} for b in snapshots]
    # Net income for the fiscal year to date: the P&L accounts' balances in _balances are
    # already this fiscal year only. A profit is a credit, so it is negated to read positive.
    pnl_ids = {a.id for a in snapshots[0].accounts if a.type in PNL_TYPES}
    net_income = [-sum((v for aid, v in b.balances.items() if aid in pnl_ids), ZERO) for b in snapshots]

    sections, totals = [], {}
    for key, label, _, _, _ in BS_SECTIONS:
        rows = _rows(accounts, values, lambda a, k=key: _section_of(a, BS_SECTIONS) == k)
        total = [sum((r["amounts"][i] for r in rows if not r["is_header"]), ZERO) for i in range(len(dates))]
        if key == "equity":
            total = [total[i] + net_income[i] for i in range(len(dates))]
        totals[key] = total
        sections.append({"key": key, "label": label, "rows": _columns_json(rows),
                         "total": [to_str(x) for x in total]})

    def add(keys):
        return [sum((totals[k][i] for k in keys), ZERO) for i in range(len(dates))]

    current_assets = add(("bank", "ar", "other_current_assets"))
    total_assets = add(("bank", "ar", "other_current_assets", "fixed_assets", "other_assets"))
    current_liabilities = add(("ap", "credit_cards", "other_current_liabilities"))
    total_liabilities = add(("ap", "credit_cards", "other_current_liabilities", "long_term_liabilities"))
    liabilities_and_equity = [total_liabilities[i] + totals["equity"][i] for i in range(len(dates))]
    return {
        "as_of": as_of.isoformat(), "compare": compare,
        "columns": [{"as_of": d.isoformat()} for d in dates],
        "fiscal_year_start": snapshots[0].fy_start.isoformat(),
        "sections": sections,
        "net_income": [to_str(x) for x in net_income],
        "total_current_assets": [to_str(x) for x in current_assets],
        "total_assets": [to_str(x) for x in total_assets],
        "total_current_liabilities": [to_str(x) for x in current_liabilities],
        "total_liabilities": [to_str(x) for x in total_liabilities],
        "total_equity": [to_str(x) for x in totals["equity"]],
        "total_liabilities_and_equity": [to_str(x) for x in liabilities_and_equity],
        "balanced": [total_assets[i] == liabilities_and_equity[i] for i in range(len(dates))],
    }


# ---------------------------------------------------------------- General Ledger detail

MAX_GL_LINES = 20000


def gl_detail(start: date, end: date, account_id: int | None = None) -> dict:
    """Every line by account for a range, with opening and closing balances.

    A P&L account's opening balance counts only its fiscal year (DESIGN.md 3.4), as the
    account register does, so a range inside one year reads like QuickBooks' report.
    """
    if end < start:
        raise LedgerError("The end date is before the start date.")
    with SessionLocal() as session:
        accounts = {a.id: a for a in session.scalars(select(Account))}
        if account_id is not None and account_id not in accounts:
            raise NotFound(f"Account {account_id} does not exist.")
        fy = fiscal_year_start(start, session.get(Settings, 1).fiscal_year_start_month)

        def opening_for(types, since=None):
            stmt = (select(JournalLine.account_id, func.sum(JournalLine.amount))
                    .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                    .where(JournalEntry.entry_date < start, JournalLine.account_id.in_(
                        [a.id for a in accounts.values() if a.type in types]))
                    .group_by(JournalLine.account_id))
            if since:
                stmt = stmt.where(JournalEntry.entry_date >= since)
            return dict(session.execute(stmt).all())

        opening = {**opening_for(("ASSET", "LIABILITY", "EQUITY")), **opening_for(PNL_TYPES, fy)}

        stmt = (select(JournalLine, JournalEntry)
                .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                .where(JournalEntry.entry_date.between(start, end)))
        if account_id is not None:
            stmt = stmt.where(JournalLine.account_id == account_id)
        rows = session.execute(stmt.order_by(JournalEntry.entry_date, JournalEntry.id, JournalLine.line_no)
                               .limit(MAX_GL_LINES + 1)).all()
        if len(rows) > MAX_GL_LINES:
            raise LedgerError(f"More than {MAX_GL_LINES} lines; choose a shorter range or one account.")

        entry_ids = {e.id for _, e in rows}
        others: dict[int, list[tuple[int, int]]] = {}
        bank_lines: dict[int, int] = {}
        payees = {}
        if entry_ids:
            for l in session.scalars(select(JournalLine).where(JournalLine.entry_id.in_(entry_ids))):
                others.setdefault(l.entry_id, []).append((l.id, l.account_id))
            bank_lines = dict(session.execute(select(BankTxn.entry_id, BankTxn.id)
                                              .where(BankTxn.entry_id.in_(entry_ids))).all())
            payee_ids = {e.payee_id for _, e in rows if e.payee_id}
            if payee_ids:
                payees = dict(session.execute(select(Payee.id, Payee.name).where(Payee.id.in_(payee_ids))).all())

    by_account: dict[int, list] = {}
    for line, entry in rows:
        by_account.setdefault(line.account_id, []).append((line, entry))
    wanted = [account_id] if account_id is not None else sorted(
        set(by_account) | {a for a, v in opening.items() if v},
        key=lambda i: accounts[i].number)

    out = []
    for aid in wanted:
        a = accounts[aid]
        sign = NORMAL_SIGN[a.type]
        running = opening.get(aid, ZERO) or ZERO
        items, debits, credits = [], ZERO, ZERO
        for line, entry in by_account.get(aid, []):
            running += line.amount
            other = sorted({accounts[o].number + " " + accounts[o].name
                            for lid, o in others.get(entry.id, []) if lid != line.id})
            debits += line.amount if line.amount > 0 else ZERO
            credits += -line.amount if line.amount < 0 else ZERO
            items.append({
                "entry_id": entry.id, "entry_date": entry.entry_date.isoformat(), "source": entry.source,
                "payee": payees.get(entry.payee_id) if entry.payee_id else None,
                "memo": line.memo or entry.memo,
                "split": other[0] if len(other) == 1 else ("-Split-" if other else None),
                "debit": to_str(line.amount) if line.amount > 0 else None,
                "credit": to_str(-line.amount) if line.amount < 0 else None,
                "balance": to_str(running * sign),
                "bank_txn_id": bank_lines.get(entry.id),
            })
        out.append({"account_id": aid, "number": a.number, "name": a.name, "type": a.type,
                    "opening": to_str((opening.get(aid, ZERO) or ZERO) * sign),
                    "lines": items, "total_debit": to_str(debits), "total_credit": to_str(credits),
                    "closing": to_str(running * sign)})
    return {"start": start.isoformat(), "end": end.isoformat(), "fiscal_year_start": fy.isoformat(),
            "accounts": out, "line_count": len(rows)}

""" EOF - statements.py """
