"""
General Ledger v0.3.0
File: utils/journal.py
Description: The accounting core (docs/DESIGN.md section 3). post_entry() is the ONLY
             code path that inserts journal_line rows, and it refuses anything that
             would unbalance, back-date past the lock, or post to a header or
             inactive account. Corrections are reversals; nothing posted is edited.

The functions taking a `session` do not commit: the caller owns the transaction, which
is what lets "Edit" reverse and re-post as one atomic change. The module-level
functions at the bottom are what routes call; each opens and commits its own.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from db import SessionLocal
from models import Account, BankAccount, BankTxn, JournalEntry, JournalLine, Settings
from utils import audit
from utils.errors import LedgerError, NotFound
from utils.money import ZERO, parse_amount, parse_date, parse_optional_amount, to_str


class JournalError(LedgerError):
    """An entry the books refuse. `problems` lists every reason, not just the first."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


# Sources the journal module reverses itself. A BANK or INVOICE entry also has a
# staging row (bank_txn, invoice) that must change in the same transaction, so their
# own modules reverse them (phases 2 and 5).
REVERSIBLE_HERE = {"MANUAL", "OPENING", "IMPORT"}

MEMO_MAX = 255


@dataclass
class LineInput:
    account_id: int
    amount: Decimal
    memo: str | None = None


@dataclass
class EntryCheck:
    problems: list[str] = field(default_factory=list)
    total_debits: Decimal = ZERO
    total_credits: Decimal = ZERO

    @property
    def difference(self) -> Decimal:
        return self.total_debits - self.total_credits

    @property
    def ok(self) -> bool:
        return not self.problems


# ---------------------------------------------------------------- parsing

def _clean_memo(value, what: str = "memo") -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LedgerError(f"{what} must be text.")
    value = value.strip()
    if len(value) > MEMO_MAX:
        raise LedgerError(f"{what} is longer than {MEMO_MAX} characters.")
    return value or None


def parse_lines(raw_lines) -> tuple[list[LineInput], list[str]]:
    """Lines from the API: [{account_id, debit, credit, memo}], one of debit/credit each.

    Rows with no account and no amount are blank grid rows and are skipped. Every other
    problem is collected, numbered by the row the owner sees, so the entry form can list
    them all at once.
    """
    if not isinstance(raw_lines, list):
        return [], ["lines must be a list."]
    lines, problems = [], []
    for n, raw in enumerate(raw_lines, start=1):
        if not isinstance(raw, dict):
            problems.append(f"Line {n} is malformed.")
            continue
        account_id = raw.get("account_id")
        debit_raw, credit_raw = raw.get("debit"), raw.get("credit")
        try:
            debit = parse_optional_amount(debit_raw, f"Line {n} debit")
            credit = parse_optional_amount(credit_raw, f"Line {n} credit")
            memo = _clean_memo(raw.get("memo"), f"Line {n} memo")
        except LedgerError as e:
            problems.append(str(e))
            continue
        if account_id in (None, "") and debit is None and credit is None:
            continue
        if account_id in (None, ""):
            problems.append(f"Line {n} has no account.")
            continue
        try:
            account_id = int(account_id)
        except (TypeError, ValueError):
            problems.append(f"Line {n} has an invalid account.")
            continue
        if debit is not None and credit is not None:
            problems.append(f"Line {n} has both a debit and a credit; use one or the other.")
            continue
        if debit is None and credit is None:
            problems.append(f"Line {n} has no amount.")
            continue
        amount = debit if debit is not None else -credit
        if (debit is not None and debit < 0) or (credit is not None and credit < 0):
            problems.append(f"Line {n} is negative; enter it in the other column instead.")
            continue
        lines.append(LineInput(account_id=account_id, amount=amount, memo=memo))
    return lines, problems


# ---------------------------------------------------------------- the rules

def _lock_date(session, for_post: bool) -> date | None:
    stmt = select(Settings.lock_date).where(Settings.id == 1)
    if for_post:
        # A shared lock: set_lock_date takes FOR UPDATE, so a lock-date move and a
        # posting cannot interleave and let a line in just behind the new lock.
        stmt = stmt.with_for_update(read=True)
    return session.execute(stmt).scalar_one()


def check_entry(session, entry_date: date, lines: list[LineInput], *, source: str = "MANUAL",
                bank_txn_ids: list[int] | None = None, for_post: bool = False) -> EntryCheck:
    """Every DESIGN.md section 3.1 rule, all problems at once."""
    check = EntryCheck()
    for line in lines:
        if line.amount > 0:
            check.total_debits += line.amount
        else:
            check.total_credits -= line.amount

    if len(lines) < 2:
        check.problems.append("An entry needs at least two lines.")
    if any(line.amount == 0 for line in lines):
        check.problems.append("A line cannot be 0.00.")
    if check.difference != 0:
        side = "debits" if check.difference > 0 else "credits"
        check.problems.append(f"Out of balance by {abs(check.difference)} ({side} are higher).")

    ids = {line.account_id for line in lines}
    if ids:
        accounts = {a.id: a for a in session.scalars(select(Account).where(Account.id.in_(ids)))}
        headers = set(session.scalars(
            select(Account.parent_id).where(Account.parent_id.in_(ids)).distinct()
        ))
        for account_id in sorted(ids):
            account = accounts.get(account_id)
            if account is None:
                check.problems.append(f"Account id {account_id} does not exist.")
            elif not account.is_active:
                check.problems.append(f"{account.number} {account.name} is inactive.")
            elif account_id in headers:
                check.problems.append(
                    f"{account.number} {account.name} is a header account; post to one of its sub-accounts."
                )

    lock = _lock_date(session, for_post)
    if lock is not None and entry_date <= lock:
        check.problems.append(f"{entry_date} is on or before the lock date ({lock}).")

    if source == "BANK":
        check.problems.extend(_bank_link_problems(session, lines, bank_txn_ids, accounts if ids else {},
                                                  for_post))
    return check


def _bank_link_problems(session, lines: list[LineInput], bank_txn_ids, accounts: dict,
                        for_post: bool) -> list[str]:
    """A bank-feed posting must be tied to the bank lines it came from (DESIGN.md 3.1).

    The entry's lines on bank and card accounts must equal, account by account, the bank
    lines it claims, and each of those must still be waiting in the queue. That is what
    makes it impossible to post one bank line twice, or to post a bank line for an amount
    the bank never showed.
    """
    if not bank_txn_ids:
        return ["A bank-feed entry must be linked to its bank line."]
    stmt = select(BankTxn).where(BankTxn.id.in_(set(bank_txn_ids)))
    if for_post:
        stmt = stmt.with_for_update()
    txns = session.scalars(stmt).all()
    problems = []
    missing = set(bank_txn_ids) - {t.id for t in txns}
    if missing:
        problems.append(f"Bank line(s) {sorted(missing)} do not exist.")
    for t in txns:
        if t.status not in ("NEW", "SUGGESTED"):
            problems.append(f"Bank line {t.id} is already {t.status.lower()}.")
    gl_of = dict(session.execute(
        select(BankAccount.id, BankAccount.gl_account_id)
        .where(BankAccount.id.in_({t.bank_account_id for t in txns}))
    ).all())
    expected: dict[int, Decimal] = {}
    for t in txns:
        gl = gl_of[t.bank_account_id]
        expected[gl] = expected.get(gl, ZERO) + t.amount
    actual: dict[int, Decimal] = {}
    for line in lines:
        account = accounts.get(line.account_id)
        if line.account_id in expected or (account is not None and account.is_bank_account):
            actual[line.account_id] = actual.get(line.account_id, ZERO) + line.amount
    if expected != actual:
        problems.append("The entry's lines on bank and card accounts do not match the bank line(s) it posts.")
    return problems


def post_entry(session, *, entry_date: date, lines: list[LineInput], memo: str | None = None,
               source: str = "MANUAL", payee_id: int | None = None,
               reverses_entry_id: int | None = None,
               bank_txn_ids: list[int] | None = None) -> JournalEntry:
    """Insert one balanced entry and its lines. Does not commit."""
    if not isinstance(entry_date, date):
        raise JournalError(["entry_date must be a date."])
    check = check_entry(session, entry_date, lines, source=source,
                        bank_txn_ids=bank_txn_ids, for_post=True)
    if not check.ok:
        raise JournalError(check.problems)

    entry = JournalEntry(
        entry_date=entry_date,
        memo=memo,
        source=source,
        payee_id=payee_id,
        reverses_entry_id=reverses_entry_id,
        created_at=audit.utcnow(),
    )
    session.add(entry)
    session.flush()
    for n, line in enumerate(lines, start=1):
        session.add(JournalLine(entry_id=entry.id, line_no=n, account_id=line.account_id,
                                amount=line.amount, memo=line.memo))
    # Marked in the same flush as the lines: a bank line is POSTED exactly when the
    # entry that posts it exists, never one without the other.
    if source == "BANK":
        for txn in session.scalars(select(BankTxn).where(BankTxn.id.in_(set(bank_txn_ids)))):
            txn.status = "POSTED"
            txn.entry_id = entry.id
    session.flush()
    session.refresh(entry)
    return entry


def reverse_entry(session, entry_id: int, *, reversal_date: date | None = None,
                  memo: str | None = None,
                  allow_sources: set[str] = REVERSIBLE_HERE) -> JournalEntry:
    """Post an entry negating every line of `entry_id`, and link the two. Does not commit.

    `allow_sources` is widened only by the module that owns a source's staging rows
    (utils/bank_queue.py for BANK), which resets those rows in the same transaction.
    """
    entry = session.execute(
        select(JournalEntry).where(JournalEntry.id == entry_id).with_for_update()
    ).scalar_one_or_none()
    if entry is None:
        raise NotFound(f"Entry {entry_id} does not exist.")
    if entry.reversed_by_entry_id is not None:
        raise JournalError([f"Entry {entry_id} was already reversed by entry {entry.reversed_by_entry_id}."])
    if entry.source == "REVERSAL":
        raise JournalError([f"Entry {entry_id} is itself a reversal; post a new entry instead."])
    if entry.source not in allow_sources:
        raise JournalError([f"A {entry.source} entry is reversed from its own page, not the journal."])

    lock = _lock_date(session, for_post=True)
    if lock is not None and entry.entry_date <= lock:
        raise JournalError([f"Entry {entry_id} is dated on or before the lock date ({lock}); "
                            "it cannot be reversed."])

    # Dated with the original by default, so the period it belonged to nets to what
    # it should have been. Never earlier than the original.
    reversal_date = reversal_date or entry.entry_date
    if reversal_date < entry.entry_date:
        raise JournalError([f"A reversal cannot be dated before the entry it reverses ({entry.entry_date})."])

    reversal = post_entry(
        session,
        entry_date=reversal_date,
        lines=[LineInput(line.account_id, -line.amount, line.memo) for line in entry.lines],
        memo=memo or f"Reversal of entry {entry.id}" + (f": {entry.memo}" if entry.memo else ""),
        source="REVERSAL",
        payee_id=entry.payee_id,
        reverses_entry_id=entry.id,
    )
    entry.reversed_by_entry_id = reversal.id
    session.flush()
    return reversal


def replace_entry(session, entry_id: int, *, entry_date: date, lines: list[LineInput],
                  memo: str | None, payee_id: int | None = None) -> tuple[JournalEntry, JournalEntry]:
    """"Edit": reverse the original and post the corrected entry. Does not commit.

    Both happen in the caller's one transaction, so an edit that fails validation
    leaves the original untouched rather than reversed with nothing in its place.
    """
    original = session.get(JournalEntry, entry_id)
    if original is None:
        raise NotFound(f"Entry {entry_id} does not exist.")
    if original.source != "MANUAL":
        raise JournalError([f"Only manual entries are edited here; entry {entry_id} is {original.source}."])
    reversal = reverse_entry(session, entry_id,
                             memo=f"Reversal of entry {entry_id} (edited)")
    replacement = post_entry(session, entry_date=entry_date, lines=lines, memo=memo,
                             source="MANUAL", payee_id=payee_id)
    return reversal, replacement


def update_memo(session, entry_id: int, memo: str | None) -> JournalEntry:
    """The one change a posted entry allows (DESIGN.md section 3.2), with an audit row."""
    entry = session.get(JournalEntry, entry_id)
    if entry is None:
        raise NotFound(f"Entry {entry_id} does not exist.")
    memo = _clean_memo(memo)
    if memo != entry.memo:
        audit.record(session, "entry.memo", "journal_entry", entry.id,
                     {"old": entry.memo, "new": memo})
        entry.memo = memo
    session.flush()
    return entry


def journal_total(session) -> Decimal:
    """SUM(amount) over the whole journal. Anything but 0.00 is a broken ledger."""
    return session.execute(select(func.coalesce(func.sum(JournalLine.amount), 0))).scalar_one()


# ---------------------------------------------------------------- serialisation

def serialize_entry(entry: JournalEntry, accounts: dict[int, Account]) -> dict:
    return {
        "id": entry.id,
        "entry_date": entry.entry_date.isoformat(),
        "memo": entry.memo,
        "source": entry.source,
        "payee_id": entry.payee_id,
        "reverses_entry_id": entry.reverses_entry_id,
        "reversed_by_entry_id": entry.reversed_by_entry_id,
        "editable": entry.source == "MANUAL" and entry.reversed_by_entry_id is None,
        "reversible": entry.source in REVERSIBLE_HERE and entry.reversed_by_entry_id is None,
        "lines": [
            {
                "line_no": line.line_no,
                "account_id": line.account_id,
                "account_number": accounts[line.account_id].number,
                "account_name": accounts[line.account_id].name,
                "amount": to_str(line.amount),
                "debit": to_str(line.amount) if line.amount > 0 else None,
                "credit": to_str(-line.amount) if line.amount < 0 else None,
                "memo": line.memo,
                "cleared": line.cleared_recon_id is not None,
            }
            for line in entry.lines
        ],
    }


def _accounts_by_id(session) -> dict[int, Account]:
    return {a.id: a for a in session.scalars(select(Account))}


def _check_json(check: EntryCheck) -> dict:
    return {
        "ok": check.ok,
        "problems": check.problems,
        "total_debits": to_str(check.total_debits),
        "total_credits": to_str(check.total_credits),
        "difference": to_str(check.difference),
    }


def _entry_payload(data: dict) -> tuple[date, list[LineInput], str | None, list[str]]:
    problems = []
    try:
        entry_date = parse_date(data.get("entry_date"), "Date")
    except LedgerError as e:
        entry_date, problems = None, [str(e)]
    try:
        memo = _clean_memo(data.get("memo"))
    except LedgerError as e:
        memo = None
        problems.append(str(e))
    lines, line_problems = parse_lines(data.get("lines"))
    return entry_date, lines, memo, problems + line_problems


# ---------------------------------------------------------------- route entry points

def validate(data: dict) -> dict:
    """The live "Out of balance by $X" check on the entry form. Posts nothing."""
    entry_date, lines, _memo, problems = _entry_payload(data)
    with SessionLocal() as session:
        if entry_date is None:
            check = EntryCheck()
            for line in lines:
                if line.amount > 0:
                    check.total_debits += line.amount
                else:
                    check.total_credits -= line.amount
        else:
            check = check_entry(session, entry_date, lines)
    check.problems = problems + check.problems
    return _check_json(check)


def create_manual(data: dict) -> dict:
    entry_date, lines, memo, problems = _entry_payload(data)
    if problems:
        raise JournalError(problems)
    with SessionLocal.begin() as session:
        entry = post_entry(session, entry_date=entry_date, lines=lines, memo=memo, source="MANUAL")
        return serialize_entry(entry, _accounts_by_id(session))


def replace_manual(entry_id: int, data: dict) -> dict:
    entry_date, lines, memo, problems = _entry_payload(data)
    if problems:
        raise JournalError(problems)
    with SessionLocal.begin() as session:
        reversal, replacement = replace_entry(session, entry_id, entry_date=entry_date,
                                              lines=lines, memo=memo)
        accounts = _accounts_by_id(session)
        return {"reversal": serialize_entry(reversal, accounts),
                "entry": serialize_entry(replacement, accounts)}


def reverse(entry_id: int, data: dict) -> dict:
    reversal_date = data.get("reversal_date")
    reversal_date = parse_date(reversal_date, "Reversal date") if reversal_date else None
    with SessionLocal.begin() as session:
        reversal = reverse_entry(session, entry_id, reversal_date=reversal_date,
                                 memo=_clean_memo(data.get("memo")))
        return serialize_entry(reversal, _accounts_by_id(session))


def set_memo(entry_id: int, memo) -> dict:
    with SessionLocal.begin() as session:
        entry = update_memo(session, entry_id, memo)
        return serialize_entry(entry, _accounts_by_id(session))


def get_entry(entry_id: int) -> dict:
    with SessionLocal() as session:
        entry = session.get(JournalEntry, entry_id)
        if entry is None:
            raise NotFound(f"Entry {entry_id} does not exist.")
        return serialize_entry(entry, _accounts_by_id(session))


def list_entries(start: date, end: date) -> list[dict]:
    """Entries by date then id, with every line, for the Journal page."""
    if end < start:
        raise LedgerError("The end date is before the start date.")
    with SessionLocal() as session:
        entries = session.scalars(
            select(JournalEntry)
            .where(JournalEntry.entry_date.between(start, end))
            .order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc())
        ).all()
        accounts = _accounts_by_id(session)
        return [serialize_entry(e, accounts) for e in entries]

""" EOF - journal.py """
