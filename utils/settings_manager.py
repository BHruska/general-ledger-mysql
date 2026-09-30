"""
General Ledger v0.2.0
File: utils/settings_manager.py
Description: Company settings and the lock date (docs/DESIGN.md section 3.4). The lock
             date is the only close: nothing on or before it is posted, edited or
             reversed. Moving it backwards needs a reason, which goes to audit_log.
"""

from datetime import date

from sqlalchemy import select

from db import SessionLocal
from models import Account, Settings
from utils import audit
from utils.errors import LedgerError
from utils.money import parse_optional_date


def serialize(s: Settings, accounts: dict[int, Account]) -> dict:
    def label(account_id):
        a = accounts[account_id]
        return f"{a.number} {a.name}"

    return {
        "company_name": s.company_name,
        "company_address": s.company_address,
        "fiscal_year_start_month": s.fiscal_year_start_month,
        "lock_date": s.lock_date.isoformat() if s.lock_date else None,
        "ar_account": label(s.ar_account_id),
        "retained_earnings_account": label(s.retained_earnings_account_id),
    }


def _accounts(session) -> dict[int, Account]:
    return {a.id: a for a in session.scalars(select(Account))}


def get_settings() -> dict:
    with SessionLocal() as session:
        return serialize(session.get(Settings, 1), _accounts(session))


def update_company(data: dict) -> dict:
    with SessionLocal.begin() as session:
        s = session.get(Settings, 1)
        changes = {}
        if "company_name" in data:
            name = (data.get("company_name") or "").strip()
            if len(name) > 120:
                raise LedgerError("Company name is longer than 120 characters.")
            changes["company_name"] = (s.company_name, name)
            s.company_name = name
        if "company_address" in data:
            address = (data.get("company_address") or "").strip() or None
            changes["company_address"] = (s.company_address, address)
            s.company_address = address
        if "fiscal_year_start_month" in data:
            month = data.get("fiscal_year_start_month")
            if not isinstance(month, int) or isinstance(month, bool) or not 1 <= month <= 12:
                raise LedgerError("Fiscal year start month must be 1-12.")
            changes["fiscal_year_start_month"] = (s.fiscal_year_start_month, month)
            s.fiscal_year_start_month = month
        changed = {k: {"old": old, "new": new} for k, (old, new) in changes.items() if old != new}
        if changed:
            audit.record(session, "settings.update", "settings", 1, changed)
        session.flush()
        return serialize(s, _accounts(session))


def set_lock_date(data: dict) -> dict:
    new = parse_optional_date(data.get("lock_date"), "Lock date")
    reason = (data.get("reason") or "").strip()
    with SessionLocal.begin() as session:
        # FOR UPDATE: post_entry reads the lock date with a shared lock, so a posting
        # in flight finishes before the date moves, and none can slip in behind it.
        s = session.execute(select(Settings).where(Settings.id == 1).with_for_update()).scalar_one()
        old = s.lock_date
        if new == old:
            return serialize(s, _accounts(session))
        if new is not None and new > date.today():
            raise LedgerError("The lock date cannot be in the future.")
        backwards = old is not None and (new is None or new < old)
        if backwards and not reason:
            raise LedgerError("Moving the lock date backwards reopens closed books; give a reason.")
        audit.record(session, "lock_date.move", "settings", 1, {
            "old": old.isoformat() if old else None,
            "new": new.isoformat() if new else None,
            "backwards": backwards,
            "reason": reason or None,
        })
        s.lock_date = new
        session.flush()
        return serialize(s, _accounts(session))

""" EOF - settings_manager.py """
