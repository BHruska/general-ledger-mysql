"""
General Ledger v0.3.0
File: utils/bank_queue.py
Description: The review queue (docs/DESIGN.md section 6). Every bank line becomes a
             journal entry only after a person posts it, splits it, or excludes it.
             Posting writes one BANK entry: the bank account for the line's amount, and
             the chosen account(s) for its negation.
"""

from decimal import Decimal

from sqlalchemy import func, select

from db import SessionLocal
from models import Account, BankAccount, BankTxn, JournalEntry, JournalLine
from utils import audit, journal
from utils.errors import LedgerError, NotFound
from utils.journal import JournalError, LineInput
from utils.money import ZERO, parse_amount, to_str

VIEWS = {
    "review": ("NEW", "SUGGESTED"),
    "excluded": ("EXCLUDED",),
    "posted": ("POSTED",),
}
REVIEWABLE = ("NEW", "SUGGESTED")
MAX_ROWS = 1000
REASON_MAX = 120


def _serialize(t: BankTxn, ba: BankAccount, offsets: dict[int, list[str]], names: dict[int, str]) -> dict:
    return {
        "id": t.id,
        "bank_account_id": ba.id,
        "bank_account": ba.name + (f" ··{ba.mask}" if ba.mask else ""),
        "posted_date": t.posted_date.isoformat(),
        "description": t.description,
        "amount": to_str(t.amount),
        "provider_category": t.provider_category,
        "status": t.status,
        "suggested_account_id": t.suggested_account_id,
        "suggested_account": names.get(t.suggested_account_id) if t.suggested_account_id else None,
        "excluded_reason": t.excluded_reason,
        "entry_id": t.entry_id,
        "posted_to": offsets.get(t.entry_id) if t.entry_id else None,
    }


def list_lines(view: str = "review", bank_account_id: int | None = None) -> dict:
    if view not in VIEWS:
        raise LedgerError(f"Unknown view {view!r}.")
    with SessionLocal() as session:
        stmt = (select(BankTxn, BankAccount)
                .join(BankAccount, BankAccount.id == BankTxn.bank_account_id)
                .where(BankTxn.status.in_(VIEWS[view])))
        if bank_account_id:
            stmt = stmt.where(BankTxn.bank_account_id == bank_account_id)
        rows = session.execute(
            stmt.order_by(BankTxn.posted_date.desc(), BankTxn.id.desc()).limit(MAX_ROWS + 1)).all()
        truncated = len(rows) > MAX_ROWS
        rows = rows[:MAX_ROWS]

        names = {a.id: f"{a.number} {a.name}" for a in session.scalars(select(Account))}
        # What each posted line was posted to: the entry's lines other than bank lines.
        entry_ids = {t.entry_id for t, _ in rows if t.entry_id}
        offsets: dict[int, list[str]] = {}
        if entry_ids:
            bank_gl = set(session.scalars(select(BankAccount.gl_account_id)))
            for line in session.scalars(select(JournalLine).where(JournalLine.entry_id.in_(entry_ids))):
                if line.account_id not in bank_gl:
                    offsets.setdefault(line.entry_id, []).append(names[line.account_id])

        counts = dict(session.execute(
            select(BankTxn.status, func.count()).group_by(BankTxn.status)).all())
        return {
            "view": view,
            "lines": [_serialize(t, ba, offsets, names) for t, ba in rows],
            "truncated": truncated,
            "counts": {
                "review": sum(counts.get(s, 0) for s in REVIEWABLE),
                "excluded": counts.get("EXCLUDED", 0),
                "posted": counts.get("POSTED", 0),
            },
        }


def _txn(session, txn_id: int, lock: bool = False) -> BankTxn:
    stmt = select(BankTxn).where(BankTxn.id == txn_id)
    if lock:
        stmt = stmt.with_for_update()
    txn = session.scalar(stmt)
    if txn is None:
        raise NotFound(f"Bank line {txn_id} does not exist.")
    return txn


def _entry_lines(session, txn: BankTxn, data: dict) -> tuple[list[LineInput], list[str], Decimal]:
    """The bank line plus its offsets, from `splits`: [{account_id, amount, memo}].

    Split amounts are portions of the bank line, entered positive in the line's own
    direction, and must add up to it. A single-account post is one split for the whole
    amount. Returns (lines, problems, remaining).
    """
    ba = session.get(BankAccount, txn.bank_account_id)
    splits = data.get("splits")
    if splits is None and data.get("account_id"):
        # The common case, one account for the whole line: the server supplies the
        # amount, so the page never computes one.
        splits = [{"account_id": data["account_id"], "amount": to_str(abs(txn.amount))}]
    if not isinstance(splits, list) or not splits:
        return [], ["Choose an account to post to."], abs(txn.amount)

    direction = 1 if txn.amount > 0 else -1
    lines = [LineInput(ba.gl_account_id, txn.amount, None)]
    problems, total = [], ZERO
    for n, split in enumerate(splits, start=1):
        if not isinstance(split, dict):
            problems.append(f"Split {n} is malformed.")
            continue
        account_id = split.get("account_id")
        try:
            portion = parse_amount(split.get("amount"), f"Split {n} amount")
            memo = journal._clean_memo(split.get("memo"), f"Split {n} memo")
        except LedgerError as e:
            problems.append(str(e))
            continue
        if not account_id:
            problems.append(f"Split {n} has no account.")
            continue
        if int(account_id) == ba.gl_account_id:
            problems.append(f"Split {n} posts the line back to its own bank account.")
            continue
        total += portion
        lines.append(LineInput(int(account_id), -portion * direction, memo))
    remaining = abs(txn.amount) - total
    if remaining != 0 and not problems:
        problems.append(f"The splits must add up to {to_str(abs(txn.amount))}; "
                        f"{to_str(abs(remaining))} {'left to assign' if remaining > 0 else 'too much'}.")
    return lines, problems, remaining


def check_post(txn_id: int, data: dict) -> dict:
    """The split dialog's live check. Posts nothing."""
    with SessionLocal() as session:
        txn = _txn(session, txn_id)
        lines, problems, remaining = _entry_lines(session, txn, data)
        if lines and not problems:
            problems = journal.check_entry(session, txn.posted_date, lines, source="BANK",
                                           bank_txn_ids=[txn.id]).problems
        return {"ok": not problems, "problems": problems, "remaining": to_str(remaining),
                "line_amount": to_str(abs(txn.amount))}


def post_line(txn_id: int, data: dict) -> dict:
    with SessionLocal.begin() as session:
        txn = _txn(session, txn_id, lock=True)
        if txn.status not in REVIEWABLE:
            raise LedgerError(f"Bank line {txn_id} is already {txn.status.lower()}.")
        lines, problems, _ = _entry_lines(session, txn, data)
        if problems:
            raise JournalError(problems)
        memo = journal._clean_memo(data.get("memo")) or txn.description[:journal.MEMO_MAX]
        entry = journal.post_entry(session, entry_date=txn.posted_date, lines=lines, memo=memo,
                                   source="BANK", bank_txn_ids=[txn.id])
        return {"entry_id": entry.id, "txn_id": txn.id}


def exclude(txn_id: int, reason) -> dict:
    reason = (reason or "").strip() if isinstance(reason, str) else ""
    if not reason:
        raise LedgerError("Say why this line is excluded (duplicate, personal, before cutover...).")
    if len(reason) > REASON_MAX:
        raise LedgerError(f"The reason is longer than {REASON_MAX} characters.")
    with SessionLocal.begin() as session:
        txn = _txn(session, txn_id, lock=True)
        if txn.status not in REVIEWABLE:
            raise LedgerError(f"Bank line {txn_id} is {txn.status.lower()}; only a line under review can be excluded.")
        txn.status = "EXCLUDED"
        txn.excluded_reason = reason
        audit.record(session, "bank_txn.exclude", "bank_txn", txn.id, {"reason": reason})
        return {"txn_id": txn.id}


def restore(txn_id: int) -> dict:
    """Put an excluded line back in the queue."""
    with SessionLocal.begin() as session:
        txn = _txn(session, txn_id, lock=True)
        if txn.status != "EXCLUDED":
            raise LedgerError(f"Bank line {txn_id} is not excluded.")
        audit.record(session, "bank_txn.restore", "bank_txn", txn.id, {"reason": txn.excluded_reason})
        txn.status = "NEW"
        txn.excluded_reason = None
        return {"txn_id": txn.id}


def unpost(txn_id: int) -> dict:
    """Reverse the line's BANK entry and send the line back to the queue.

    The original entry and its reversal both stay in the journal (DESIGN.md 3.2); only
    the bank line returns to NEW. If the entry posted several lines at once (a transfer,
    phase 2b), every one of them returns.
    """
    with SessionLocal.begin() as session:
        txn = _txn(session, txn_id, lock=True)
        if txn.status != "POSTED" or txn.entry_id is None:
            raise LedgerError(f"Bank line {txn_id} is not posted.")
        entry_id = txn.entry_id
        reversal = journal.reverse_entry(
            session, entry_id, memo=f"Unposted bank line {txn.id}: {txn.description}"[:journal.MEMO_MAX],
            allow_sources={"BANK"},
        )
        returned = session.scalars(select(BankTxn).where(BankTxn.entry_id == entry_id).with_for_update()).all()
        for t in returned:
            t.status = "NEW"
            t.entry_id = None
        audit.record(session, "bank_txn.unpost", "journal_entry", entry_id,
                     {"reversal_entry_id": reversal.id, "bank_txn_ids": [t.id for t in returned]})
        return {"reversal_entry_id": reversal.id, "returned": [t.id for t in returned]}

""" EOF - bank_queue.py """
