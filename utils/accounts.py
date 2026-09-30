"""
General Ledger v0.2.0
File: utils/accounts.py
Description: The chart of accounts (docs/DESIGN.md section 3.3). Sub-accounts one level
             deep, a parent with children is a header that cannot take postings, and an
             account with postings is deactivated, never deleted.
"""

from sqlalchemy import exists, func, select

from db import SessionLocal
from models import ACCOUNT_TYPES, NUMBER_RANGES, Account, JournalLine, Payee, Settings
from utils.errors import LedgerError, NotFound

TEXT_LIMITS = {"name": 100, "description": 255, "tax_line": 60}


def _has_postings(session, account_id: int) -> bool:
    return session.execute(
        select(exists().where(JournalLine.account_id == account_id))
    ).scalar()


def _has_children(session, account_id: int) -> bool:
    return session.execute(select(exists().where(Account.parent_id == account_id))).scalar()


def _settings_refs(session) -> dict[int, str]:
    s = session.get(Settings, 1)
    return {s.ar_account_id: "Accounts Receivable", s.retained_earnings_account_id: "Retained Earnings"}


def _text(data: dict, key: str, required: bool = False) -> str | None:
    value = data.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise LedgerError(f"{key.replace('_', ' ').capitalize()} is required.")
        return None
    if not isinstance(value, str):
        raise LedgerError(f"{key} must be text.")
    value = value.strip()
    if len(value) > TEXT_LIMITS[key]:
        raise LedgerError(f"{key} is longer than {TEXT_LIMITS[key]} characters.")
    return value


def _flag(data: dict, key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise LedgerError(f"{key} must be true or false.")
    return value


def _check_number(session, number, type_: str, own_id: int | None = None) -> str:
    if not isinstance(number, str) or not number.strip().isdigit():
        raise LedgerError("Account number must be digits only, e.g. 6120.")
    number = number.strip()
    low, high = NUMBER_RANGES[type_]
    if not low <= int(number) <= high:
        raise LedgerError(f"A {type_.lower()} account is numbered {low}-{high}; {number} is outside that.")
    clash = session.scalar(select(Account).where(Account.number == number))
    if clash is not None and clash.id != own_id:
        raise LedgerError(f"Account number {number} is already {clash.name}.")
    return number


def _check_parent(session, parent_id, type_: str, own_id: int | None = None) -> int | None:
    if parent_id in (None, ""):
        return None
    parent = session.get(Account, int(parent_id))
    if parent is None:
        raise LedgerError("The parent account does not exist.")
    if parent.id == own_id:
        raise LedgerError("An account cannot be its own parent.")
    if parent.parent_id is not None:
        raise LedgerError(f"{parent.number} is already a sub-account; sub-accounts go one level deep.")
    if parent.type != type_:
        raise LedgerError(f"{parent.number} is {parent.type.lower()}; a sub-account has its parent's type.")
    if own_id is not None and _has_children(session, own_id):
        raise LedgerError("This account has sub-accounts of its own, so it cannot become one.")
    # Becoming a header would strand the postings already on it: headers take none.
    if _has_postings(session, parent.id):
        raise LedgerError(f"{parent.number} {parent.name} has postings, so it cannot become a header.")
    return parent.id


def serialize(account: Account, *, has_postings: bool, is_header: bool, protected: str | None) -> dict:
    return {
        "id": account.id,
        "number": account.number,
        "name": account.name,
        "type": account.type,
        "parent_id": account.parent_id,
        "is_active": account.is_active,
        "is_bank_account": account.is_bank_account,
        "tax_line": account.tax_line,
        "is_1099_expense": account.is_1099_expense,
        "description": account.description,
        "is_header": is_header,
        "has_postings": has_postings,
        # Can the owner post to it from the entry form?
        "postable": account.is_active and not is_header,
        # Why it cannot be deleted or deactivated, if it cannot.
        "protected": protected,
        "deletable": not has_postings and not is_header and protected is None,
    }


def list_accounts() -> list[dict]:
    """Every account in number order, the sort key of every report."""
    with SessionLocal() as session:
        accounts = session.scalars(select(Account).order_by(Account.number)).all()
        posted = set(session.scalars(select(JournalLine.account_id).distinct()))
        headers = set(session.scalars(
            select(Account.parent_id).where(Account.parent_id.isnot(None)).distinct()
        ))
        refs = _settings_refs(session)
        return [serialize(a, has_postings=a.id in posted, is_header=a.id in headers,
                          protected=refs.get(a.id)) for a in accounts]


def create_account(data: dict) -> dict:
    type_ = data.get("type")
    if type_ not in ACCOUNT_TYPES:
        raise LedgerError(f"Type must be one of {', '.join(ACCOUNT_TYPES)}.")
    with SessionLocal.begin() as session:
        account = Account(
            number=_check_number(session, data.get("number"), type_),
            name=_text(data, "name", required=True),
            type=type_,
            parent_id=_check_parent(session, data.get("parent_id"), type_),
            is_active=True,
            is_bank_account=_flag(data, "is_bank_account", False),
            tax_line=_text(data, "tax_line"),
            is_1099_expense=_flag(data, "is_1099_expense", False),
            description=_text(data, "description"),
        )
        if account.is_1099_expense and type_ != "EXPENSE":
            raise LedgerError("Only an expense account can be a 1099 expense.")
        session.add(account)
        session.flush()
        return serialize(account, has_postings=False, is_header=False, protected=None)


def update_account(account_id: int, data: dict) -> dict:
    with SessionLocal.begin() as session:
        account = session.get(Account, account_id)
        if account is None:
            raise NotFound(f"Account {account_id} does not exist.")
        has_postings = _has_postings(session, account_id)
        refs = _settings_refs(session)

        type_ = data.get("type", account.type)
        if type_ != account.type:
            if type_ not in ACCOUNT_TYPES:
                raise LedgerError(f"Type must be one of {', '.join(ACCOUNT_TYPES)}.")
            # Changing the type flips its normal sign and which statement it lands on,
            # silently rewriting every report it has ever appeared in.
            if has_postings or _has_children(session, account_id):
                raise LedgerError("The type of an account with postings or sub-accounts cannot change.")
            account.type = type_

        if "number" in data:
            account.number = _check_number(session, data["number"], account.type, own_id=account_id)
        elif type_ != account.type:
            _check_number(session, account.number, account.type, own_id=account_id)
        if "name" in data:
            account.name = _text(data, "name", required=True)
        if "description" in data:
            account.description = _text(data, "description")
        if "tax_line" in data:
            account.tax_line = _text(data, "tax_line")
        if "is_bank_account" in data:
            account.is_bank_account = _flag(data, "is_bank_account", account.is_bank_account)
        if "is_1099_expense" in data:
            account.is_1099_expense = _flag(data, "is_1099_expense", account.is_1099_expense)
            if account.is_1099_expense and account.type != "EXPENSE":
                raise LedgerError("Only an expense account can be a 1099 expense.")
        if "parent_id" in data:
            new_parent = data["parent_id"] or None
            if new_parent != account.parent_id:
                account.parent_id = _check_parent(session, new_parent, account.type, own_id=account_id)
        if "is_active" in data:
            active = _flag(data, "is_active", account.is_active)
            if not active and account_id in refs:
                raise LedgerError(f"This is the {refs[account_id]} account in Settings; it must stay active.")
            account.is_active = active

        session.flush()
        return serialize(account, has_postings=has_postings,
                         is_header=_has_children(session, account_id), protected=refs.get(account_id))


def delete_account(account_id: int) -> None:
    with SessionLocal.begin() as session:
        account = session.get(Account, account_id)
        if account is None:
            raise NotFound(f"Account {account_id} does not exist.")
        if _has_postings(session, account_id):
            raise LedgerError(f"{account.number} {account.name} has postings; deactivate it instead.")
        if _has_children(session, account_id):
            raise LedgerError(f"{account.number} {account.name} has sub-accounts; move or delete them first.")
        refs = _settings_refs(session)
        if account_id in refs:
            raise LedgerError(f"This is the {refs[account_id]} account in Settings.")
        if session.scalar(select(func.count()).select_from(Payee).where(Payee.default_account_id == account_id)):
            raise LedgerError("A payee uses this as its default account.")
        session.delete(account)

""" EOF - accounts.py """
