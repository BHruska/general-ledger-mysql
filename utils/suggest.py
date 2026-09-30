"""
General Ledger v0.4.0
File: utils/suggest.py
Description: Suggestions for bank lines in review (docs/DESIGN.md sections 6.3-6.4).
             Suggestions only: nothing here posts, and only a person moves a line to
             POSTED or EXCLUDED.

Strongest first, and the first that applies wins:

  TRANSFER   a card payment seen on both feeds: equal and opposite amounts within five
             days, one side looking like a card payment (or matching a TRANSFER rule).
             With only one side in, TRANSFER_WAITING: the line waits rather than posts.
  RULE       the owner's payee rules, in priority order.
  PAYEE      an ACTIVE payee's name found in the bank text; its default account.
  HISTORY    the account most used in the last twelve months for the same bank text.

Local database work only, so it runs in the web process straight after an import, a
posting with "Remember", or a rule change -- no outbound call is involved.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select

from db import SessionLocal
from models import Account, BankAccount, BankTxn, JournalLine, Payee, PayeeRule

REVIEWABLE = ("NEW", "SUGGESTED")
TRANSFER_WINDOW = timedelta(days=5)
HISTORY_WINDOW = timedelta(days=365)
PAYEE_NAME_MIN = 3

# What a card payment looks like from either side, normalised (see normalise()).
CARD_PAYMENT_TEXT = ("automatic payment", "payment thank you", "chase credit crd", "autopay",
                     "epay", "payment to chase card")


def normalise(text: str | None) -> str:
    """Lower case, punctuation to spaces, runs of spaces collapsed: "HOSTINGER* HOSTINGER.C"
    and "hostinger.com" both contain "hostinger"."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", (text or "").lower()).split())


def history_key(text: str | None) -> str:
    """Bank text with every token containing a digit dropped, so the same merchant with a
    different reference number ("AMZN Mktp US*2C10Y9VQ0") is recognised as the same."""
    return " ".join(t for t in normalise(text).split() if not any(c.isdigit() for c in t))


def rule_matches(rule: PayeeRule, txn: BankTxn) -> bool:
    if rule.bank_account_id and rule.bank_account_id != txn.bank_account_id:
        return False
    size = abs(txn.amount)
    if rule.amount_min is not None and size < rule.amount_min:
        return False
    if rule.amount_max is not None and size > rule.amount_max:
        return False
    subject = txn.merchant_name if rule.match_field == "MERCHANT" else txn.description
    if not subject:
        return False
    if rule.match_type == "REGEX":
        try:
            return re.search(rule.pattern, subject, re.IGNORECASE) is not None
        except re.error:
            return False  # refused at save; a bad pattern here matches nothing
    s, p = normalise(subject), normalise(rule.pattern)
    if not p:
        return False
    if rule.match_type == "EQUALS":
        return s == p
    if rule.match_type == "STARTS_WITH":
        return s.startswith(p)
    return re.search(r"(?<![0-9a-z])" + re.escape(p) + r"(?![0-9a-z])", s) is not None


# Lines whose bank text names no payee: a paper check ("CHECK 1028") or a check deposit
# ("REMOTE ONLINE DEPOSIT # 1"). Learning from their text would teach "every check is
# Sales Tax", so they are never remembered, never grouped as similar, never learned from
# history and never suggested from it. Chase's CSV types them; the text is the fallback.
ANONYMOUS_CATEGORIES = {"CHECK_PAID", "CHECK_DEPOSIT"}
_ANONYMOUS_TEXT = re.compile(r"^\s*(check|chk|remote online deposit|deposit)\b[\s#:]*\d*\s*$", re.IGNORECASE)


def is_anonymous(txn) -> bool:
    return ((txn.provider_category or "").strip().upper() in ANONYMOUS_CATEGORIES
            or bool(_ANONYMOUS_TEXT.match(txn.description or "")))


def looks_like_card_payment(txn: BankTxn) -> bool:
    if (txn.provider_category or "").strip().lower() == "payment":
        return True  # the Chase card CSV's own Type for a payment
    text = normalise(txn.description)
    return any(p in text for p in CARD_PAYMENT_TEXT)


@dataclass
class Suggestion:
    reason: str
    account_id: int | None = None
    payee_id: int | None = None
    rule_id: int | None = None
    transfer_txn_id: int | None = None


class Suggester:
    """Everything a pass needs, loaded once, so a pass over the queue is a handful of queries."""

    def __init__(self, session, today: date | None = None):
        self.session = session
        self.rules = session.scalars(
            select(PayeeRule).where(PayeeRule.is_active.is_(True)).order_by(PayeeRule.priority, PayeeRule.id)
        ).all()
        headers = set(session.scalars(select(Account.parent_id).where(Account.parent_id.isnot(None))))
        self.postable = set(session.scalars(select(Account.id).where(Account.is_active.is_(True)))) - headers
        self.payees = []
        for p in session.scalars(select(Payee).where(Payee.is_active.is_(True))):
            name = normalise(p.name)
            if len(name) >= PAYEE_NAME_MIN:
                rx = re.compile(r"(?<![0-9a-z])" + re.escape(name) + r"(?![0-9a-z])")
                self.payees.append((len(name), p, rx))
        self.payees.sort(key=lambda t: -t[0])  # the longest (most specific) name wins
        self.history = self._history((today or date.today()) - HISTORY_WINDOW)

    def _history(self, since: date) -> dict[str, Counter]:
        bank_gl = set(self.session.scalars(select(BankAccount.gl_account_id)))
        rows = self.session.execute(
            select(BankTxn, JournalLine.account_id)
            .join(JournalLine, JournalLine.entry_id == BankTxn.entry_id)
            .where(BankTxn.status == "POSTED", BankTxn.posted_date >= since)
        ).all()
        history: dict[str, Counter] = defaultdict(Counter)
        for txn, account_id in rows:
            if account_id not in bank_gl and not is_anonymous(txn):
                history[history_key(txn.description)][account_id] += 1
        return history

    def _usable(self, account_id: int | None) -> int | None:
        """A suggestion must be postable today: an account deactivated or turned into a
        header since the rule or payee was set up is not suggested."""
        return account_id if account_id in self.postable else None

    def for_line(self, txn: BankTxn) -> Suggestion | None:
        for rule in self.rules:
            if rule.action == "TRANSFER" or not rule_matches(rule, txn):
                continue
            if rule.action == "EXCLUDE":
                return Suggestion("RULE_EXCLUDE", rule_id=rule.id, payee_id=rule.payee_id)
            return Suggestion("RULE", self._usable(rule.account_id), rule.payee_id, rule.id)
        if is_anonymous(txn):
            return None  # only a rule the owner wrote may speak for a check
        text = normalise(txn.description)
        for _, payee, rx in self.payees:
            if rx.search(text):
                account = self._usable(payee.default_account_id)
                if account:
                    return Suggestion("PAYEE", account, payee.id)
                past = self.history.get(history_key(txn.description))
                if past:
                    return Suggestion("HISTORY", self._usable(past.most_common(1)[0][0]), payee.id)
                return Suggestion("PAYEE", None, payee.id)
        past = self.history.get(history_key(txn.description))
        if past:
            return Suggestion("HISTORY", self._usable(past.most_common(1)[0][0]))
        return None

    def is_transfer_candidate(self, txn: BankTxn) -> bool:
        if looks_like_card_payment(txn):
            return True
        return any(r.action == "TRANSFER" and rule_matches(r, txn) for r in self.rules)


def _pair_transfers(lines: list[BankTxn], suggester: Suggester) -> dict[int, Suggestion]:
    """Match card payments across feeds: equal and opposite amounts, within five days,
    closest date first. Each line pairs at most once."""
    out: dict[int, Suggestion] = {}
    candidates = [t for t in lines if suggester.is_transfer_candidate(t)]
    taken: set[int] = set()
    for t in sorted(candidates, key=lambda t: (t.posted_date, t.id)):
        if t.id in taken:
            continue
        others = [o for o in lines
                  if o.id != t.id and o.id not in taken and o.bank_account_id != t.bank_account_id
                  and o.amount == -t.amount and abs(o.posted_date - t.posted_date) <= TRANSFER_WINDOW]
        if others:
            o = min(others, key=lambda o: (abs(o.posted_date - t.posted_date), o.id))
            taken.update((t.id, o.id))
            out[t.id] = Suggestion("TRANSFER", transfer_txn_id=o.id)
            out[o.id] = Suggestion("TRANSFER", transfer_txn_id=t.id)
        else:
            out[t.id] = Suggestion("TRANSFER_WAITING")
    return out


def run(session, today: date | None = None) -> dict:
    """Recompute every suggestion in the review queue. Does not commit.

    Recomputed from scratch each time rather than patched, so a changed rule, payee or
    archived vendor is reflected everywhere at once, and a pass is idempotent.
    """
    lines = session.scalars(select(BankTxn).where(BankTxn.status.in_(REVIEWABLE)).with_for_update()).all()
    suggester = Suggester(session, today)
    transfers = _pair_transfers(lines, suggester)
    counts: Counter = Counter()
    for t in lines:
        s = transfers.get(t.id) or suggester.for_line(t)
        t.suggested_account_id = s.account_id if s else None
        t.suggested_payee_id = s.payee_id if s else None
        t.suggested_rule_id = s.rule_id if s else None
        t.suggested_transfer_txn_id = s.transfer_txn_id if s else None
        t.suggestion_reason = s.reason if s else None
        # SUGGESTED means "one click posts (or excludes) it"; a line with nothing
        # actionable stays NEW even when a payee was recognised.
        actionable = s is not None and (s.account_id or s.reason in ("TRANSFER", "RULE_EXCLUDE"))
        t.status = "SUGGESTED" if actionable else "NEW"
        counts[s.reason if s else "NONE"] += 1
    return {"lines": len(lines), "suggested": sum(1 for t in lines if t.status == "SUGGESTED"),
            "by_reason": dict(counts)}


def run_now() -> dict:
    with SessionLocal.begin() as session:
        return run(session)

""" EOF - suggest.py """
