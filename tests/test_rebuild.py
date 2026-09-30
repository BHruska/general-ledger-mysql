"""
General Ledger v0.6.1
File: tests/test_rebuild.py
Description: The rebuild's "learning": rules, payee edits and settings saved by account
             number and payee name, and restored onto rebuilt books; and the refusal to
             reset anything but a local database.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, text

import config
import db
from models import Account, Payee, PayeeRule, Settings
from utils import journal, rules
from utils.errors import LedgerError
from utils.migration import rebuild


def test_learning_round_trip_by_number_and_name(chart):
    with db.SessionLocal.begin() as session:
        session.add(Payee(name="Acme Hosting", is_vendor=True, default_account_id=chart["6110"], is_active=True))
        s = session.get(Settings, 1)
        s.company_name, s.zelle_recipient = "Example Co", "pay@example.com"
    rules.create_rule({"pattern": "ACME", "account_id": chart["6110"], "amount_max": "50.00"})
    learning = rebuild.save_learning()
    assert learning["rules"][0]["account"] == "6110" and learning["payees"][0]["default_account"] == "6110"

    # "Rebuild": new ids for the same accounts, no payees or rules.
    with db.engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for t in ("payee_rule", "payee"):
            conn.execute(text(f"DELETE FROM {t}"))
        conn.execute(text("UPDATE account SET id = id + 1000 WHERE number = '6110'"))
        conn.execute(text("UPDATE settings SET company_name = '', zelle_recipient = NULL"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

    r = rebuild.restore_learning(learning)
    assert (r["rules"], r["payees"], r["unresolved"]) == (1, 1, [])
    with db.SessionLocal() as session:
        hosting = session.scalar(select(Account).where(Account.number == "6110"))
        rule = session.scalars(select(PayeeRule)).one()
        assert rule.account_id == hosting.id and rule.amount_max == Decimal("50.00")
        assert session.scalar(select(Payee)).default_account_id == hosting.id
        assert session.get(Settings, 1).zelle_recipient == "pay@example.com"


def test_unresolvable_learning_is_reported_not_guessed(chart):
    learning = {"rules": [{"priority": 100, "match_field": "DESCRIPTION", "match_type": "CONTAINS", "pattern": "X",
                           "bank_account": None, "amount_min": None, "amount_max": None, "payee": None,
                           "account": "9999", "action": "SUGGEST", "memo_template": None, "times_applied": 0,
                           "is_active": True}], "payees": [], "settings": {}}
    r = rebuild.restore_learning(learning)
    assert r["rules"] == 0 and r["unresolved"] == ["rule 'X': account 9999"]


def test_history_gaps_both_ways(chart):
    """The Q3 rehearsal, in miniature: an unaccepted deposit and a payment entered twice."""
    csv_text = (Path(__file__).resolve().parent / "fixtures" / "chase_checking.csv").read_text()
    history = [(date(2026, 9, 20), "-115.98"),    # Chase 09/21: QuickBooks a day earlier
               (date(2026, 9, 18), "-179.88"),
               (date(2026, 9, 17), "-2071.25"),
               (date(2026, 9, 25), "225.00"),     # nothing in Chase: entered twice
               (date(2026, 1, 5), "999.00")]      # before the file's first line: not judged
    with db.SessionLocal.begin() as session:
        for when, amount in history:
            journal.post_entry(session, entry_date=when, source="IMPORT", memo=f"QBO {amount}", lines=[
                journal.LineInput(chart["1010"], Decimal(amount)),
                journal.LineInput(chart["6300"], -Decimal(amount))])
    with db.SessionLocal() as session:
        gaps = rebuild.history_gaps(session, chart["1010"], csv_text, date(2026, 10, 1))
    assert [(m["date"], m["amount"]) for m in gaps["not_in_history"]] == [("2026-09-28", "1500.00")]
    assert [(m["date"], m["amount"]) for m in gaps["not_in_chase"]] == [("2026-09-25", "225.00")]
    # Lines on or after the boundary are the feed's, not the check's.
    with db.SessionLocal() as session:
        assert rebuild.history_gaps(session, chart["1010"], csv_text, date(2026, 9, 28))["not_in_history"] == []


def test_reset_refuses_a_remote_database(monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", "mysql+pymysql://gl:secret@db.production.example:3306/gl")
    with pytest.raises(LedgerError, match="only a local development database"):
        rebuild.reset_dev_database()

""" EOF - test_rebuild.py """
