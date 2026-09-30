"""
General Ledger v0.3.0
File: utils/bank_accounts.py
Description: Feed accounts (docs/DESIGN.md section 5): each links one GL bank or card
             account to a connection. Phase 2a creates FILE-fed accounts; Plaid-fed
             ones arrive in phase 4 on the same table.
"""

from datetime import date

from sqlalchemy import func, select

from db import SessionLocal
from models import Account, BankAccount, BankConnection, BankTxn, JournalLine
from utils import audit
from utils.errors import LedgerError, NotFound
from utils.feeds import file_import
from utils.money import parse_date, to_str

KIND_FOR_TYPE = {"ASSET": "DEPOSITORY", "LIABILITY": "CREDIT"}


def _file_connection(session, institution: str) -> BankConnection:
    """One FILE pseudo-connection per institution, so accounts group the way Plaid's will."""
    conn = session.scalar(select(BankConnection).where(
        BankConnection.provider == "FILE", BankConnection.institution == institution))
    if conn is None:
        conn = BankConnection(provider="FILE", institution=institution, status="OK")
        session.add(conn)
        session.flush()
    return conn


def _mask(value) -> str | None:
    if value in (None, ""):
        return None
    value = str(value).strip()
    if not value.isdigit() or len(value) > 8:
        raise LedgerError("The mask is the last digits of the account number (up to 8 digits).")
    return value


def _name(value) -> str:
    value = (value or "").strip() if isinstance(value, str) else ""
    if not value:
        raise LedgerError("Name is required.")
    if len(value) > 100:
        raise LedgerError("Name is longer than 100 characters.")
    return value


def list_bank_accounts() -> list[dict]:
    with SessionLocal() as session:
        rows = session.execute(
            select(BankAccount, BankConnection, Account)
            .join(BankConnection, BankConnection.id == BankAccount.connection_id)
            .join(Account, Account.id == BankAccount.gl_account_id)
            .order_by(Account.number)
        ).all()
        counts = {
            (acct_id, status): n for acct_id, status, n in session.execute(
                select(BankTxn.bank_account_id, BankTxn.status, func.count())
                .group_by(BankTxn.bank_account_id, BankTxn.status))
        }
        gl_balances = dict(session.execute(
            select(JournalLine.account_id, func.sum(JournalLine.amount)).group_by(JournalLine.account_id)
        ).all())
        out = []
        for ba, conn, gl in rows:
            sign = 1 if gl.type == "ASSET" else -1
            gl_balance = gl_balances.get(gl.id)
            last = file_import.last_import(session, ba.id)
            out.append({
                "id": ba.id,
                "name": ba.name,
                "mask": ba.mask,
                "kind": ba.kind,
                "provider": conn.provider,
                "institution": conn.institution,
                "gl_account_id": gl.id,
                "gl_account": f"{gl.number} {gl.name}",
                "feed_start_date": ba.feed_start_date.isoformat(),
                # Both in the account's normal direction: a card shows what is owed.
                "gl_balance": to_str(gl_balance * sign) if gl_balance is not None else "0.00",
                "reported_balance": to_str(ba.reported_balance * sign) if ba.reported_balance is not None else None,
                "reported_balance_at": ba.reported_balance_at.date().isoformat() if ba.reported_balance_at else None,
                "to_review": counts.get((ba.id, "NEW"), 0) + counts.get((ba.id, "SUGGESTED"), 0),
                "posted": counts.get((ba.id, "POSTED"), 0),
                "excluded": counts.get((ba.id, "EXCLUDED"), 0),
                "last_import_at": last.isoformat() if last else None,
                "deletable": not any(counts.get((ba.id, s), 0) for s in
                                     ("NEW", "SUGGESTED", "POSTED", "EXCLUDED", "REMOVED")),
            })
        return out


def eligible_gl_accounts() -> list[dict]:
    """GL accounts a feed can be attached to: bank accounts not already linked."""
    with SessionLocal() as session:
        linked = set(session.scalars(select(BankAccount.gl_account_id)))
        accounts = session.scalars(select(Account).where(
            Account.is_bank_account.is_(True), Account.is_active.is_(True),
            Account.type.in_(tuple(KIND_FOR_TYPE))).order_by(Account.number)).all()
        return [{"id": a.id, "label": f"{a.number} {a.name}", "kind": KIND_FOR_TYPE[a.type]}
                for a in accounts if a.id not in linked]


def create_file_account(data: dict) -> dict:
    with SessionLocal.begin() as session:
        gl = session.get(Account, int(data.get("gl_account_id") or 0))
        if gl is None:
            raise LedgerError("Choose the GL account this feed posts to.")
        if not gl.is_bank_account or gl.type not in KIND_FOR_TYPE:
            raise LedgerError(f"{gl.number} {gl.name} is not marked as a bank or card account.")
        if session.scalar(select(BankAccount).where(BankAccount.gl_account_id == gl.id)):
            raise LedgerError(f"{gl.number} {gl.name} already has a feed account.")
        institution = (data.get("institution") or "Chase").strip()[:100]
        ba = BankAccount(
            connection_id=_file_connection(session, institution).id,
            gl_account_id=gl.id,
            kind=KIND_FOR_TYPE[gl.type],
            mask=_mask(data.get("mask")),
            name=_name(data.get("name")),
            feed_start_date=parse_date(data.get("feed_start_date"), "Feed start date"),
        )
        session.add(ba)
        session.flush()
        audit.record(session, "bank_account.create", "bank_account", ba.id,
                     {"gl_account_id": gl.id, "feed_start_date": ba.feed_start_date.isoformat()})
        return {"id": ba.id}


def update_bank_account(bank_account_id: int, data: dict) -> dict:
    with SessionLocal.begin() as session:
        ba = session.get(BankAccount, bank_account_id)
        if ba is None:
            raise NotFound(f"Bank account {bank_account_id} does not exist.")
        changes = {}
        if "name" in data:
            ba.name = _name(data["name"])
        if "mask" in data:
            ba.mask = _mask(data["mask"])
        if "feed_start_date" in data:
            new: date = parse_date(data["feed_start_date"], "Feed start date")
            if new != ba.feed_start_date:
                # Lines already imported stay; the date only decides what future imports keep.
                changes["feed_start_date"] = {"old": ba.feed_start_date.isoformat(), "new": new.isoformat()}
                ba.feed_start_date = new
        if changes:
            audit.record(session, "bank_account.update", "bank_account", ba.id, changes)
        return {"id": ba.id}


def delete_bank_account(bank_account_id: int) -> None:
    with SessionLocal.begin() as session:
        ba = session.get(BankAccount, bank_account_id)
        if ba is None:
            raise NotFound(f"Bank account {bank_account_id} does not exist.")
        if session.scalar(select(func.count()).select_from(BankTxn).where(BankTxn.bank_account_id == ba.id)):
            raise LedgerError(f"{ba.name} has imported lines; it cannot be deleted.")
        session.delete(ba)

""" EOF - bank_accounts.py """
