"""
General Ledger v0.4.0
File: utils/bank_queue.py
Description: The review queue (docs/DESIGN.md section 6). Every bank line becomes a
             journal entry only after a person posts it, splits it, or excludes it.
             Posting writes one BANK entry: the bank account for the line's amount, and
             the chosen account(s) for its negation. A transfer between two feeds is ONE
             entry linking both lines.

Suggestions (utils/suggest.py) are recomputed after anything that changes what is in
review or what a suggestion would be: an import, a restore, an undo, a remembered rule.
"""

from decimal import Decimal

from sqlalchemy import func, select

from db import SessionLocal
from models import Account, BankAccount, BankTxn, JournalLine, Payee, PayeeRule
from utils import audit, journal, rules, suggest
from utils.errors import LedgerError, NotFound
from utils.journal import JournalError, LineInput
from utils.money import ZERO, parse_amount, to_str

VIEWS = {
    "review": ("NEW", "SUGGESTED"),
    "excluded": ("EXCLUDED",),
    "posted": ("POSTED",),
}
REVIEWABLE = suggest.REVIEWABLE
MAX_ROWS = 1000
REASON_MAX = 120


def _serialize(t: BankTxn, ba: BankAccount, ctx: dict) -> dict:
    other = ctx["txns"].get(t.suggested_transfer_txn_id) if t.suggested_transfer_txn_id else None
    rule = ctx["rules"].get(t.suggested_rule_id) if t.suggested_rule_id else None
    return {
        "id": t.id,
        "bank_account_id": ba.id,
        "bank_account": ctx["banks"][ba.id],
        "posted_date": t.posted_date.isoformat(),
        "description": t.description,
        "amount": to_str(t.amount),
        "provider_category": t.provider_category,
        "status": t.status,
        "suggestion_reason": t.suggestion_reason,
        "suggested_account_id": t.suggested_account_id,
        "suggested_account": ctx["names"].get(t.suggested_account_id) if t.suggested_account_id else None,
        "suggested_payee_id": t.suggested_payee_id,
        "suggested_payee": ctx["payees"].get(t.suggested_payee_id) if t.suggested_payee_id else None,
        "suggested_rule": rule.pattern if rule else None,
        "transfer_with": {
            "id": other.id, "bank_account": ctx["banks"][other.bank_account_id],
            "posted_date": other.posted_date.isoformat(), "description": other.description,
        } if other else None,
        "excluded_reason": t.excluded_reason,
        "entry_id": t.entry_id,
        "posted_to": ctx["offsets"].get(t.entry_id) if t.entry_id else None,
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
        banks = {b.id: b.name + (f" ··{b.mask}" if b.mask else "") for b in session.scalars(select(BankAccount))}
        # What each posted line was posted to: the entry's lines other than bank lines.
        entry_ids = {t.entry_id for t, _ in rows if t.entry_id}
        offsets: dict[int, list[str]] = {}
        if entry_ids:
            bank_gl = set(session.scalars(select(BankAccount.gl_account_id)))
            for line in session.scalars(select(JournalLine).where(JournalLine.entry_id.in_(entry_ids))):
                target = offsets.setdefault(line.entry_id, [])
                if line.account_id not in bank_gl:
                    target.append(names[line.account_id])
            for entry_id, targets in offsets.items():
                if not targets:
                    targets.append("Transfer between bank accounts")
        pair_ids = {t.suggested_transfer_txn_id for t, _ in rows if t.suggested_transfer_txn_id}
        ctx = {
            "names": names,
            "banks": banks,
            "offsets": offsets,
            "payees": dict(session.execute(select(Payee.id, Payee.name).where(
                Payee.id.in_({t.suggested_payee_id for t, _ in rows if t.suggested_payee_id} or {0}))).all()),
            "rules": {r.id: r for r in session.scalars(select(PayeeRule))},
            "txns": {t.id: t for t in session.scalars(select(BankTxn).where(BankTxn.id.in_(pair_ids or {0})))},
        }

        counts = dict(session.execute(
            select(BankTxn.status, func.count()).group_by(BankTxn.status)).all())
        return {
            "view": view,
            "lines": [_serialize(t, ba, ctx) for t, ba in rows],
            "truncated": truncated,
            "counts": {
                "review": sum(counts.get(s, 0) for s in REVIEWABLE),
                "suggested": counts.get("SUGGESTED", 0),
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


def _touch_payee(session, payee_id: int | None, when) -> None:
    """A posting is a use: keep last_used_on current, and bring an archived payee back."""
    if not payee_id:
        return
    payee = session.get(Payee, payee_id)
    if payee is None:
        raise LedgerError("That payee does not exist.")
    if payee.last_used_on is None or payee.last_used_on < when:
        payee.last_used_on = when
    payee.is_active = True


def _post(session, txn: BankTxn, data: dict) -> dict:
    """Post one line inside the caller's transaction."""
    if txn.status not in REVIEWABLE:
        raise LedgerError(f"Bank line {txn.id} is already {txn.status.lower()}.")
    if txn.suggestion_reason == "TRANSFER" and not data.get("splits") and not data.get("account_id"):
        return _post_transfer(session, txn)
    lines, problems, _ = _entry_lines(session, txn, data)
    if problems:
        raise JournalError(problems)
    payee_id = data.get("payee_id", txn.suggested_payee_id) or None
    memo = journal._clean_memo(data.get("memo")) or txn.description[:journal.MEMO_MAX]

    single = len(lines) == 2
    chosen = lines[1].account_id if single else None
    accepted_unchanged = single and chosen == txn.suggested_account_id
    if accepted_unchanged and txn.suggested_rule_id:
        rule = session.get(PayeeRule, txn.suggested_rule_id)
        if rule is not None:
            rule.times_applied += 1

    entry = journal.post_entry(session, entry_date=txn.posted_date, lines=lines, memo=memo,
                               source="BANK", payee_id=payee_id, bank_txn_ids=[txn.id])
    _touch_payee(session, payee_id, txn.posted_date)

    remembered = None
    if data.get("remember") and single:
        rule = rules.remember(session, txn, chosen, payee_id)
        remembered = {"id": rule.id, "pattern": rule.pattern}
    return {"entry_id": entry.id, "txn_id": txn.id, "remembered": remembered}


def _post_transfer(session, txn: BankTxn) -> dict:
    """ONE entry for both sides of a card payment (DESIGN.md 6.3), linking both lines."""
    other = _txn(session, txn.suggested_transfer_txn_id, lock=True) if txn.suggested_transfer_txn_id else None
    if other is None or other.status not in REVIEWABLE or other.suggested_transfer_txn_id != txn.id:
        raise LedgerError("The other side of this transfer is not waiting in review.")
    gl = dict(session.execute(select(BankAccount.id, BankAccount.gl_account_id)
                              .where(BankAccount.id.in_((txn.bank_account_id, other.bank_account_id)))).all())
    names = dict(session.execute(select(BankAccount.id, BankAccount.name)
                                 .where(BankAccount.id.in_((txn.bank_account_id, other.bank_account_id)))).all())
    out_side, in_side = (txn, other) if txn.amount < 0 else (other, txn)
    # Both lines are dated by their own bank; the entry takes the later date, when the
    # money had arrived on both sides.
    entry = journal.post_entry(
        session, entry_date=max(txn.posted_date, other.posted_date),
        lines=[LineInput(gl[in_side.bank_account_id], in_side.amount, in_side.description[:255]),
               LineInput(gl[out_side.bank_account_id], out_side.amount, out_side.description[:255])],
        memo=f"Transfer: {names[out_side.bank_account_id]} to {names[in_side.bank_account_id]}",
        source="BANK", bank_txn_ids=[txn.id, other.id])
    return {"entry_id": entry.id, "txn_id": txn.id, "transfer_txn_id": other.id, "remembered": None}


def post_line(txn_id: int, data: dict) -> dict:
    with SessionLocal.begin() as session:
        txn = _txn(session, txn_id, lock=True)
        result = _post(session, txn, data)
        if result["remembered"]:
            # The new or updated rule applies to everything still in review at once.
            suggest.run(session)
        return result


def post_suggested(bank_account_id: int | None = None) -> dict:
    """"Post all suggested": each line in its own transaction, so one refusal (a lock
    date, a deactivated account) never blocks the rest -- and is reported, not hidden."""
    with SessionLocal() as session:
        stmt = select(BankTxn.id).where(BankTxn.status == "SUGGESTED")
        if bank_account_id:
            stmt = stmt.where(BankTxn.bank_account_id == bank_account_id)
        ids = list(session.scalars(stmt.order_by(BankTxn.posted_date, BankTxn.id)))
    posted, excluded, refused, done = 0, 0, [], set()
    for txn_id in ids:
        if txn_id in done:
            continue  # the other half of a transfer already posted
        try:
            with SessionLocal.begin() as session:
                txn = _txn(session, txn_id, lock=True)
                if txn.status != "SUGGESTED":
                    continue
                if txn.suggestion_reason == "RULE_EXCLUDE":
                    rule = session.get(PayeeRule, txn.suggested_rule_id)
                    _exclude(session, txn, f"Rule: {rule.pattern}"[:REASON_MAX] if rule else "Rule")
                    excluded += 1
                    continue
                data = {} if txn.suggestion_reason == "TRANSFER" else {"account_id": txn.suggested_account_id}
                result = _post(session, txn, data)
                done.update(i for i in (result["txn_id"], result.get("transfer_txn_id")) if i)
                posted += 1
        except LedgerError as e:
            refused.append({"txn_id": txn_id, "error": str(e)})
    return {"posted": posted, "excluded": excluded, "refused": refused}


def _exclude(session, txn: BankTxn, reason: str) -> None:
    if txn.status not in REVIEWABLE:
        raise LedgerError(f"Bank line {txn.id} is {txn.status.lower()}; only a line under review can be excluded.")
    txn.status = "EXCLUDED"
    txn.excluded_reason = reason
    audit.record(session, "bank_txn.exclude", "bank_txn", txn.id, {"reason": reason})


def exclude(txn_id: int, reason) -> dict:
    reason = (reason or "").strip() if isinstance(reason, str) else ""
    if not reason:
        raise LedgerError("Say why this line is excluded (duplicate, personal, before cutover...).")
    if len(reason) > REASON_MAX:
        raise LedgerError(f"The reason is longer than {REASON_MAX} characters.")
    with SessionLocal.begin() as session:
        _exclude(session, _txn(session, txn_id, lock=True), reason)
        suggest.run(session)  # a transfer partner may now be waiting alone
        return {"txn_id": txn_id}


def restore(txn_id: int) -> dict:
    """Put an excluded line back in the queue."""
    with SessionLocal.begin() as session:
        txn = _txn(session, txn_id, lock=True)
        if txn.status != "EXCLUDED":
            raise LedgerError(f"Bank line {txn_id} is not excluded.")
        audit.record(session, "bank_txn.restore", "bank_txn", txn.id, {"reason": txn.excluded_reason})
        txn.status = "NEW"
        txn.excluded_reason = None
        suggest.run(session)
        return {"txn_id": txn.id}


def unpost(txn_id: int) -> dict:
    """Reverse the line's BANK entry and send the line back to the queue.

    The original entry and its reversal both stay in the journal (DESIGN.md 3.2); only
    the bank line returns to review. A transfer returns both of its lines.
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
        suggest.run(session)
        return {"reversal_entry_id": reversal.id, "returned": [t.id for t in returned]}


def refresh_suggestions() -> dict:
    return suggest.run_now()

""" EOF - bank_queue.py """
