"""
General Ledger v0.3.3
File: utils/payees.py
Description: Vendors and customers (docs/DESIGN.md section 4, payee). An archived payee
             (is_active = FALSE) keeps its history but stays out of pickers and
             suggestions; "archive unused" does that in bulk by last-used date.
"""

from datetime import date

from sqlalchemy import func, select, update

from db import SessionLocal
from models import Account, Payee
from utils import audit
from utils.errors import LedgerError, NotFound
from utils.money import parse_date

VIEWS = ("active", "archived", "all")


def serialize(p: Payee, labels: dict[int, str]) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "is_vendor": p.is_vendor,
        "is_customer": p.is_customer,
        "is_active": p.is_active,
        "is_1099_vendor": p.is_1099_vendor,
        "default_account_id": p.default_account_id,
        "default_account": labels.get(p.default_account_id) if p.default_account_id else None,
        "last_used_on": p.last_used_on.isoformat() if p.last_used_on else None,
        "email": p.email,
        "address": p.address,
    }


def _labels(session) -> dict[int, str]:
    return {a.id: f"{a.number} {a.name}" for a in session.scalars(select(Account))}


def list_payees(view: str = "active") -> dict:
    if view not in VIEWS:
        raise LedgerError(f"Unknown view {view!r}.")
    with SessionLocal() as session:
        stmt = select(Payee).order_by(Payee.name)
        if view != "all":
            stmt = stmt.where(Payee.is_active.is_(view == "active"))
        labels = _labels(session)
        counts = dict(session.execute(select(Payee.is_active, func.count()).group_by(Payee.is_active)).all())
        return {
            "view": view,
            "payees": [serialize(p, labels) for p in session.scalars(stmt)],
            "counts": {"active": counts.get(True, 0), "archived": counts.get(False, 0)},
        }


def _default_account(session, value) -> int | None:
    if value in (None, ""):
        return None
    account = session.get(Account, int(value))
    if account is None:
        raise LedgerError("That default account does not exist.")
    if session.scalar(select(func.count()).select_from(Account).where(Account.parent_id == account.id)):
        raise LedgerError(f"{account.number} {account.name} is a header account; choose a sub-account.")
    if account.is_bank_account:
        raise LedgerError("A bank or card account cannot be a payee's default; that is a transfer.")
    return account.id


def _flag(data, key, current):
    value = data.get(key, current)
    if not isinstance(value, bool):
        raise LedgerError(f"{key} must be true or false.")
    return value


def update_payee(payee_id: int, data: dict) -> dict:
    with SessionLocal.begin() as session:
        p = session.get(Payee, payee_id)
        if p is None:
            raise NotFound(f"Payee {payee_id} does not exist.")
        before = serialize(p, {})
        if "name" in data:
            name = " ".join((data.get("name") or "").split())
            if not name:
                raise LedgerError("Name is required.")
            if len(name) > 120:
                raise LedgerError("Name is longer than 120 characters.")
            clash = session.scalar(select(Payee).where(Payee.name == name, Payee.id != payee_id))
            if clash:
                raise LedgerError(f"Another payee is already called {clash.name}.")
            p.name = name
        if "default_account_id" in data:
            p.default_account_id = _default_account(session, data["default_account_id"])
        for key in ("is_vendor", "is_customer", "is_active", "is_1099_vendor"):
            if key in data:
                setattr(p, key, _flag(data, key, getattr(p, key)))
        session.flush()
        after = serialize(p, {})
        changes = {k: {"old": before[k], "new": after[k]} for k in after if before[k] != after[k]}
        if changes:
            audit.record(session, "payee.update", "payee", p.id, changes)
        return serialize(p, _labels(session))


def archive_unused(data: dict) -> dict:
    """Archive every active payee not used since `before` (never-used ones included)."""
    before: date = parse_date(data.get("before"), "Not used since")
    with SessionLocal.begin() as session:
        stale = (Payee.is_active.is_(True)) & ((Payee.last_used_on < before) | Payee.last_used_on.is_(None))
        n = session.scalar(select(func.count()).select_from(Payee).where(stale))
        if n:
            session.execute(update(Payee).where(stale).values(is_active=False))
            audit.record(session, "payees.archive_unused", "payee", None,
                         {"before": before.isoformat(), "archived": n})
        return {"archived": n}

""" EOF - payees.py """
