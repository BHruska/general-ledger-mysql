"""
General Ledger v0.4.0
File: utils/rules.py
Description: Payee rules (docs/DESIGN.md section 6.4): "description contains X ->
             account Y". Managed on Setup -> Rules and learned by "Remember" when a bank
             line is posted. Every change re-runs the suggestions for the queue.
"""

import re

from sqlalchemy import func, select

from db import SessionLocal
from models import Account, BankAccount, BankTxn, Payee, PayeeRule
from utils import audit, suggest
from utils.errors import LedgerError, NotFound
from utils.money import parse_optional_amount, to_str

MATCH_FIELDS = ("DESCRIPTION", "MERCHANT")
MATCH_TYPES = ("CONTAINS", "STARTS_WITH", "EQUALS", "REGEX")
ACTIONS = ("SUGGEST", "EXCLUDE", "TRANSFER")
PATTERN_MAX = 200

_ACH_NAME = re.compile(r"ORIG CO NAME:\s*(.+?)\s+ORIG ID:", re.IGNORECASE)


def derive_keyword(description: str) -> str:
    """The part of a bank line's text worth remembering.

    Chase ACH lines carry the payer or payee after "ORIG CO NAME:" and a trace number
    after it that changes every time; card lines end in reference numbers. Tokens with
    digits are dropped, and at most three words kept, so the rule recognises the next
    charge from the same merchant rather than only this one.
    """
    m = _ACH_NAME.search(description)
    if m:
        text = m.group(1)
    else:
        text = description
    words = [w for w in text.split() if not any(c.isdigit() for c in w)]
    keyword = " ".join(words[:3]).strip(" -*#:/.,")
    return keyword or " ".join(text.split())[:40]


def serialize(r: PayeeRule, accounts: dict[int, str], payees: dict[int, str], banks: dict[int, str]) -> dict:
    return {
        "id": r.id,
        "priority": r.priority,
        "match_field": r.match_field,
        "match_type": r.match_type,
        "pattern": r.pattern,
        "bank_account_id": r.bank_account_id,
        "bank_account": banks.get(r.bank_account_id) if r.bank_account_id else None,
        "amount_min": to_str(r.amount_min),
        "amount_max": to_str(r.amount_max),
        "payee_id": r.payee_id,
        "payee": payees.get(r.payee_id) if r.payee_id else None,
        "account_id": r.account_id,
        "account": accounts.get(r.account_id) if r.account_id else None,
        "action": r.action,
        "times_applied": r.times_applied,
        "is_active": r.is_active,
    }


def _labels(session):
    accounts = {a.id: f"{a.number} {a.name}" for a in session.scalars(select(Account))}
    payees = dict(session.execute(select(Payee.id, Payee.name)).all())
    banks = dict(session.execute(select(BankAccount.id, BankAccount.name)).all())
    return accounts, payees, banks


def _review_lines(session) -> list[BankTxn]:
    return session.scalars(select(BankTxn).where(BankTxn.status.in_(suggest.REVIEWABLE))).all()


def list_rules() -> dict:
    with SessionLocal() as session:
        labels = _labels(session)
        lines = _review_lines(session)
        rules = session.scalars(select(PayeeRule).order_by(PayeeRule.priority, PayeeRule.id)).all()
        out = []
        for r in rules:
            row = serialize(r, *labels)
            # How many lines now in review this rule matches -- so a too-broad pattern
            # shows up before it misleads.
            row["matches_in_review"] = sum(1 for t in lines if suggest.rule_matches(r, t))
            out.append(row)
        return {"rules": out}


def _apply_fields(session, rule: PayeeRule, data: dict) -> None:
    if "pattern" in data:
        pattern = (data.get("pattern") or "").strip() if isinstance(data.get("pattern"), str) else ""
        if not pattern:
            raise LedgerError("The pattern is required.")
        if len(pattern) > PATTERN_MAX:
            raise LedgerError(f"The pattern is longer than {PATTERN_MAX} characters.")
        rule.pattern = pattern
    for key, allowed in (("match_field", MATCH_FIELDS), ("match_type", MATCH_TYPES), ("action", ACTIONS)):
        if key in data:
            if data[key] not in allowed:
                raise LedgerError(f"{key} must be one of {', '.join(allowed)}.")
            setattr(rule, key, data[key])
    if rule.match_type == "REGEX":
        try:
            re.compile(rule.pattern)
        except re.error as e:
            raise LedgerError(f"The pattern is not a valid regular expression: {e}") from None
    if "priority" in data:
        if not isinstance(data["priority"], int) or isinstance(data["priority"], bool) or not 0 <= data["priority"] <= 9999:
            raise LedgerError("Priority is a whole number 0-9999; lower wins.")
        rule.priority = data["priority"]
    if "amount_min" in data:
        rule.amount_min = parse_optional_amount(data["amount_min"], "Minimum amount")
    if "amount_max" in data:
        rule.amount_max = parse_optional_amount(data["amount_max"], "Maximum amount")
    if rule.amount_min is not None and rule.amount_max is not None and rule.amount_min > rule.amount_max:
        raise LedgerError("The minimum amount is above the maximum.")
    if "bank_account_id" in data:
        rule.bank_account_id = data["bank_account_id"] or None
        if rule.bank_account_id and session.get(BankAccount, rule.bank_account_id) is None:
            raise LedgerError("That bank account does not exist.")
    if "payee_id" in data:
        rule.payee_id = data["payee_id"] or None
        if rule.payee_id and session.get(Payee, rule.payee_id) is None:
            raise LedgerError("That payee does not exist.")
    if "account_id" in data:
        rule.account_id = data["account_id"] or None
    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            raise LedgerError("is_active must be true or false.")
        rule.is_active = data["is_active"]

    if rule.action == "SUGGEST":
        if not rule.account_id and not rule.payee_id:
            raise LedgerError("A suggest rule needs an account (and optionally a payee).")
    if rule.account_id:
        account = session.get(Account, rule.account_id)
        if account is None:
            raise LedgerError("That account does not exist.")
        if account.is_bank_account:
            raise LedgerError("A rule cannot post to a bank or card account; use a TRANSFER rule.")
        if session.scalar(select(func.count()).select_from(Account).where(Account.parent_id == account.id)):
            raise LedgerError(f"{account.number} {account.name} is a header; choose a sub-account.")


def create_rule(data: dict) -> dict:
    with SessionLocal.begin() as session:
        rule = PayeeRule(priority=100, match_field="DESCRIPTION", match_type="CONTAINS", action="SUGGEST",
                         pattern="", times_applied=0, is_active=True)
        _apply_fields(session, rule, {"pattern": None, **data})
        session.add(rule)
        session.flush()
        audit.record(session, "rule.create", "payee_rule", rule.id, {"pattern": rule.pattern, "action": rule.action})
        suggest.run(session)
        return serialize(rule, *_labels(session))


def update_rule(rule_id: int, data: dict) -> dict:
    with SessionLocal.begin() as session:
        rule = session.get(PayeeRule, rule_id)
        if rule is None:
            raise NotFound(f"Rule {rule_id} does not exist.")
        _apply_fields(session, rule, data)
        audit.record(session, "rule.update", "payee_rule", rule.id, {k: data[k] for k in data if k != "id"})
        suggest.run(session)
        return serialize(rule, *_labels(session))


def delete_rule(rule_id: int) -> None:
    with SessionLocal.begin() as session:
        rule = session.get(PayeeRule, rule_id)
        if rule is None:
            raise NotFound(f"Rule {rule_id} does not exist.")
        audit.record(session, "rule.delete", "payee_rule", rule.id, {"pattern": rule.pattern})
        session.delete(rule)
        session.flush()
        suggest.run(session)


def remember(session, txn: BankTxn, account_id: int, payee_id: int | None) -> PayeeRule:
    """"Remember for this payee": one rule per keyword, updated rather than duplicated.

    Does not commit and does not re-run suggestions; the caller does both.
    """
    keyword = derive_keyword(txn.description)
    existing = next((r for r in session.scalars(select(PayeeRule).where(
        PayeeRule.match_field == "DESCRIPTION", PayeeRule.match_type == "CONTAINS",
        PayeeRule.action == "SUGGEST", PayeeRule.bank_account_id.is_(None)))
        if suggest.normalise(r.pattern) == suggest.normalise(keyword)), None)
    if existing:
        existing.account_id = account_id
        existing.payee_id = payee_id or existing.payee_id
        existing.is_active = True
        audit.record(session, "rule.remember", "payee_rule", existing.id,
                     {"pattern": existing.pattern, "account_id": account_id, "updated": True})
        return existing
    rule = PayeeRule(priority=100, match_field="DESCRIPTION", match_type="CONTAINS", pattern=keyword,
                     account_id=account_id, payee_id=payee_id, action="SUGGEST", times_applied=0,
                     is_active=True)
    session.add(rule)
    session.flush()
    audit.record(session, "rule.remember", "payee_rule", rule.id,
                 {"pattern": keyword, "account_id": account_id, "updated": False})
    return rule


def preview_pattern(data: dict) -> dict:
    """Which review lines a pattern would match, before saving it."""
    probe = PayeeRule(priority=0, match_field=data.get("match_field", "DESCRIPTION"),
                      match_type=data.get("match_type", "CONTAINS"), pattern=(data.get("pattern") or "").strip(),
                      bank_account_id=data.get("bank_account_id") or None,
                      amount_min=parse_optional_amount(data.get("amount_min"), "Minimum amount"),
                      amount_max=parse_optional_amount(data.get("amount_max"), "Maximum amount"),
                      action="SUGGEST", is_active=True)
    if not probe.pattern:
        return {"matches": 0, "sample": []}
    with SessionLocal() as session:
        hits = [t for t in _review_lines(session) if suggest.rule_matches(probe, t)]
        return {"matches": len(hits), "sample": [t.description for t in hits[:5]]}

""" EOF - rules.py """
