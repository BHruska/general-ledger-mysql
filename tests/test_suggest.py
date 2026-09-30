"""
General Ledger v0.4.0
File: tests/test_suggest.py
Description: Phase 2b: suggestions (transfer, rule, payee, history), Remember, transfers
             posted once, Post all suggested, and rule management.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, text

import db
from models import BankTxn, JournalEntry, Payee, PayeeRule
from utils import bank_accounts, bank_queue, journal, rules, settings_manager, suggest
from utils.errors import LedgerError
from utils.feeds import file_import

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CARD_CSV = (FIXTURES / "chase_card.csv").read_text()
CHECKING_CSV = (FIXTURES / "chase_checking.csv").read_text()


@pytest.fixture(autouse=True)
def books_always_balance():
    yield
    with db.SessionLocal() as session:
        assert journal.journal_total(session) == 0


@pytest.fixture
def feeds(chart):
    ids = {}
    for key, gl, name in (("card", "2010", "Card"), ("checking", "1010", "Checking")):
        ids[key] = bank_accounts.create_file_account(
            {"gl_account_id": chart[gl], "name": name, "feed_start_date": "2026-07-01"})["id"]
    return ids


def add_payee(name, account_id=None, active=True):
    with db.SessionLocal.begin() as session:
        p = Payee(name=name, is_vendor=True, default_account_id=account_id, is_active=active,
                  last_used_on=date(2024, 5, 1))
        session.add(p)
        session.flush()
        return p.id


def line(description_start: str) -> BankTxn:
    with db.SessionLocal() as session:
        return next(t for t in session.scalars(select(BankTxn)) if t.description.startswith(description_start))


def rerun():
    return suggest.run_now()


# ------------------------------------------------------------------ helpers

@pytest.mark.parametrize("description, keyword", [
    ("ORIG CO NAME:ASTOUND ORIG ID:0000835355 DESC DATE:260921 CO ENTRY", "ASTOUND"),
    ("ORIG CO NAME:Square Inc ORIG ID:9424300002 DESC DATE:260914", "Square Inc"),
    ("AMZN Mktp US*2C10Y9VQ0", "AMZN Mktp"),
    ("Zelle payment from EXAMPLE CUSTOMER 1AB2CD3EF", "Zelle payment from"),
    ("OPENAI *CHATGPT SUBSCR", "OPENAI *CHATGPT SUBSCR"),
    ("CHECK 1029", "CHECK"),
])
def test_derive_keyword(description, keyword):
    assert rules.derive_keyword(description) == keyword


def test_normalise_and_history_key():
    assert suggest.normalise("HOSTINGER* HOSTINGER.C") == "hostinger hostinger c"
    assert suggest.history_key("AMZN Mktp US*2C10Y9VQ0") == suggest.history_key("AMZN Mktp US*9ZZ1")


# ------------------------------------------------------------------ transfers

def test_card_payment_pairs_across_feeds(chart, feeds):
    file_import.import_file(feeds["card"], CARD_CSV, None)
    assert line("Payment Thank You").suggestion_reason == "TRANSFER_WAITING"
    file_import.import_file(feeds["checking"], CHECKING_CSV, None)
    card, chk = line("Payment Thank You"), line("ORIG CO NAME:CHASE CREDIT CRD")
    assert (card.suggestion_reason, card.suggested_transfer_txn_id) == ("TRANSFER", chk.id)
    assert (chk.suggestion_reason, chk.suggested_transfer_txn_id) == ("TRANSFER", card.id)
    assert card.status == chk.status == "SUGGESTED"


def test_transfer_posts_once_and_undoes_both(chart, feeds):
    file_import.import_file(feeds["card"], CARD_CSV, None)
    file_import.import_file(feeds["checking"], CHECKING_CSV, None)
    card = line("Payment Thank You")
    r = bank_queue.post_line(card.id, {})
    with db.SessionLocal() as session:
        entry = session.get(JournalEntry, r["entry_id"])
        assert {(l.account_id, l.amount) for l in entry.lines} == {(chart["2010"], Decimal("2071.25")),
                                                                    (chart["1010"], Decimal("-2071.25"))}
        assert entry.entry_date == date(2026, 9, 18)
    both = [line("Payment Thank You"), line("ORIG CO NAME:CHASE CREDIT CRD")]
    assert {t.status for t in both} == {"POSTED"} and {t.entry_id for t in both} == {r["entry_id"]}
    back = bank_queue.unpost(card.id)
    assert sorted(back["returned"]) == sorted(t.id for t in both)
    assert line("Payment Thank You").suggestion_reason == "TRANSFER"   # paired again


# ------------------------------------------------------------------ rule / payee / history

def test_payee_name_suggests_default_account_only_when_active(chart, feeds):
    add_payee("Example Hosting", chart["6110"])
    add_payee("Coffee Shop", chart["6300"], active=False)
    file_import.import_file(feeds["card"], CARD_CSV, None)
    hosting = line("EXAMPLE HOSTING")
    assert (hosting.suggestion_reason, hosting.suggested_account_id, hosting.status) == ("PAYEE", chart["6110"], "SUGGESTED")
    coffee = line("COFFEE SHOP")
    assert coffee.suggestion_reason is None and coffee.status == "NEW"   # archived payees stay quiet


def test_rule_beats_payee_and_priority_orders_rules(chart, feeds):
    add_payee("Example Hosting", chart["6110"])
    rules.create_rule({"pattern": "hosting", "account_id": chart["6120"], "priority": 50})
    rules.create_rule({"pattern": "example hosting", "account_id": chart["6300"], "priority": 10})
    file_import.import_file(feeds["card"], CARD_CSV, None)
    hosting = line("EXAMPLE HOSTING")
    assert (hosting.suggestion_reason, hosting.suggested_account_id) == ("RULE", chart["6300"])


def test_rule_filters_and_exclude(chart, feeds):
    rules.create_rule({"pattern": "coffee", "action": "EXCLUDE"})
    rules.create_rule({"pattern": "example", "account_id": chart["6120"], "amount_max": "25.00",
                       "bank_account_id": feeds["card"]})
    file_import.import_file(feeds["card"], CARD_CSV, None)
    assert line("COFFEE SHOP").suggestion_reason == "RULE_EXCLUDE" and line("COFFEE SHOP").status == "SUGGESTED"
    assert line("EXAMPLE SAAS").suggested_account_id == chart["6120"]      # 20.00, within the limit
    assert line("EXAMPLE HOSTING").suggestion_reason is None               # 49.00, over it


def test_history_suggests_what_was_used_before(chart, feeds):
    file_import.import_file(feeds["card"], CARD_CSV, None)
    bank_queue.post_line(line("EXAMPLE SAAS").id, {"account_id": chart["6120"]})
    later = CARD_CSV.replace("Memo\n", "Memo\n09/29/2026,09/29/2026,EXAMPLE SAAS SUBSCR,Office & Shipping,Sale,-20.00,\n", 1)
    file_import.import_file(feeds["card"], later, None)
    with db.SessionLocal() as session:
        new = session.scalar(select(BankTxn).where(BankTxn.posted_date == date(2026, 9, 29)))
        assert (new.suggestion_reason, new.suggested_account_id) == ("HISTORY", chart["6120"])


# ------------------------------------------------------------------ remember and accepting

def test_remember_creates_one_rule_and_suggests_the_rest(chart, feeds):
    file_import.import_file(feeds["card"], CARD_CSV, None)
    coffees = [t for t in bank_queue.list_lines("review")["lines"] if t["description"] == "COFFEE SHOP"]
    r = bank_queue.post_line(coffees[0]["id"], {"account_id": chart["6300"], "remember": True})
    assert r["remembered"]["pattern"] == "COFFEE SHOP"
    other = next(t for t in bank_queue.list_lines("review")["lines"] if t["description"] == "COFFEE SHOP")
    assert (other["suggestion_reason"], other["suggested_account_id"]) == ("RULE", chart["6300"])
    # Remembering the same text again updates the rule instead of adding a second one.
    bank_queue.post_line(other["id"], {"account_id": chart["6120"], "remember": True})
    with db.SessionLocal() as session:
        found = session.scalars(select(PayeeRule)).all()
        assert len(found) == 1 and found[0].account_id == chart["6120"]


def test_accepting_a_rule_unchanged_counts(chart, feeds):
    rule = rules.create_rule({"pattern": "coffee", "account_id": chart["6300"]})
    file_import.import_file(feeds["card"], CARD_CSV, None)
    first = line("COFFEE SHOP")
    bank_queue.post_line(first.id, {"account_id": chart["6300"]})
    with db.SessionLocal() as session:
        assert session.get(PayeeRule, rule["id"]).times_applied == 1


def test_posting_with_a_payee_updates_last_used_and_reactivates(chart, feeds):
    pid = add_payee("Coffee Shop", None, active=False)
    rules.create_rule({"pattern": "coffee", "account_id": chart["6300"], "payee_id": pid})
    file_import.import_file(feeds["card"], CARD_CSV, None)
    r = bank_queue.post_line(line("COFFEE SHOP").id, {"account_id": chart["6300"]})
    with db.SessionLocal() as session:
        payee = session.get(Payee, pid)
        assert payee.last_used_on == date(2026, 9, 21) and payee.is_active
        assert session.get(JournalEntry, r["entry_id"]).payee_id == pid


def test_post_all_suggested_reports_refusals(chart, feeds):
    add_payee("Example Hosting", chart["6110"])
    add_payee("Example Saas", chart["6120"])
    rules.create_rule({"pattern": "coffee", "action": "EXCLUDE"})
    file_import.import_file(feeds["card"], CARD_CSV, None)
    file_import.import_file(feeds["checking"], CHECKING_CSV, None)
    settings_manager.set_lock_date({"lock_date": "2026-09-15"})   # EXAMPLE HOSTING is dated 09/11
    r = bank_queue.post_suggested()
    assert r["posted"] == 2          # EXAMPLE SAAS, and the transfer once for both sides
    assert r["excluded"] == 2        # both coffees
    assert len(r["refused"]) == 1 and "lock date" in r["refused"][0]["error"]
    assert line("EXAMPLE HOSTING").status == "SUGGESTED"


def test_excluding_one_side_leaves_the_other_waiting(chart, feeds):
    file_import.import_file(feeds["card"], CARD_CSV, None)
    file_import.import_file(feeds["checking"], CHECKING_CSV, None)
    bank_queue.exclude(line("ORIG CO NAME:CHASE CREDIT CRD").id, "Duplicate")
    assert line("Payment Thank You").suggestion_reason == "TRANSFER_WAITING"


# ------------------------------------------------------------------ rule management

def test_rule_validation(chart, feeds):
    with pytest.raises(LedgerError, match="regular expression"):
        rules.create_rule({"pattern": "(", "match_type": "REGEX", "account_id": chart["6300"]})
    with pytest.raises(LedgerError, match="header"):
        rules.create_rule({"pattern": "x", "account_id": chart["6100"]})
    with pytest.raises(LedgerError, match="TRANSFER rule"):
        rules.create_rule({"pattern": "x", "account_id": chart["1010"]})
    with pytest.raises(LedgerError, match="needs an account"):
        rules.create_rule({"pattern": "x"})


def test_rule_list_counts_matches_and_delete_resuggests(chart, feeds):
    file_import.import_file(feeds["card"], CARD_CSV, None)
    rule = rules.create_rule({"pattern": "coffee", "account_id": chart["6300"]})
    listed = rules.list_rules()["rules"][0]
    assert listed["matches_in_review"] == 2
    assert rules.preview_pattern({"pattern": "example"})["matches"] == 3
    rules.delete_rule(rule["id"])
    assert line("COFFEE SHOP").suggestion_reason is None


def test_api_endpoints(signed_in, chart, feeds):
    body = {"bank_account_id": feeds["card"], "content": CARD_CSV}
    imported = signed_in.post("/api/banking/import", json=body).get_json()["result"]
    assert imported["suggestions"]["by_reason"]["TRANSFER_WAITING"] == 1
    assert signed_in.post("/api/rules", json={"pattern": "coffee", "account_id": chart["6300"]}).status_code == 200
    lines = signed_in.get("/api/banking/lines?view=review").get_json()
    assert lines["counts"]["suggested"] == 2
    coffee = next(l for l in lines["lines"] if l["description"] == "COFFEE SHOP")
    assert (coffee["suggestion_reason"], coffee["suggested_rule"]) == ("RULE", "coffee")
    assert signed_in.post("/api/banking/post-suggested", json={}).get_json()["posted"] == 2
    assert signed_in.post("/api/banking/suggest", json={}).status_code == 200
    for path in ("/setup/rules", "/banking/review"):
        assert signed_in.get(path).status_code == 200

""" EOF - test_suggest.py """
