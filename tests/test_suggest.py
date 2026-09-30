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
from models import BankTxn, JournalEntry, Payee, PayeeRule, Settings
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


def test_remember_is_limited_to_the_lines_bank_account(chart, feeds):
    file_import.import_file(feeds["card"], CARD_CSV, None)
    r = bank_queue.post_line(line("EXAMPLE HOSTING").id, {"account_id": chart["6110"], "remember": True})
    with db.SessionLocal() as session:
        rule = session.get(PayeeRule, r["remembered"]["id"])
        assert rule.bank_account_id == feeds["card"]
    # The same text in checking is not claimed by the card's rule.
    file_import.import_file(feeds["checking"], CHECKING_CSV.replace("CHECK 1029  ", "EXAMPLE HOSTING REFUND"), None)
    assert line("EXAMPLE HOSTING REFUND").suggestion_reason is None


def test_an_exact_invoice_amount_outranks_a_rule(chart, feeds):
    from utils import invoices
    with db.SessionLocal.begin() as session:
        session.get(Settings, 1).default_income_account_id = chart["4000"]
    customer = invoices.create_customer({"name": "Distant Client"})["id"]
    inv = invoices.issue(invoices.save_draft({"customer_id": customer, "issue_date": "2026-09-01",
                                              "lines": [{"description": "Hosting", "rate": "1500"}]})["id"])["id"]
    rules.create_rule({"pattern": "zelle", "account_id": chart["6300"]})
    file_import.import_file(feeds["checking"], CHECKING_CSV, None)
    zelle = line("Zelle payment")
    assert (zelle.suggestion_reason, zelle.suggested_invoice_id) == ("INVOICE_AMOUNT", inv)


# ------------------------------------------------------------------ checks name no payee

@pytest.mark.parametrize("description, category, anonymous", [
    ("CHECK 1028", "CHECK_PAID", True),
    ("CHECK 1028  ", "", True),                        # text alone is enough
    ("REMOTE ONLINE DEPOSIT # 1", "CHECK_DEPOSIT", True),
    ("REMOTE ONLINE DEPOSIT # 1", "", True),
    ("CHECKFREE PAYMENT", "", False),                  # a merchant that starts with "CHECK"
    ("ORIG CO NAME:INTUIT ORIG ID:1 CO ENTRY DESCR:DEPOSIT", "ACH_CREDIT", False),
])
def test_is_anonymous(description, category, anonymous):
    assert suggest.is_anonymous(BankTxn(description=description, provider_category=category)) is anonymous


def test_a_check_is_never_remembered_grouped_or_learned(chart, feeds):
    two_checks = CHECKING_CSV.replace(
        "Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #\n",
        "Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #\n"
        "CHECK,09/25/2026,\"CHECK 1030  \",-30.00,CHECK_PAID,9000.00,1030,\n", 1)
    file_import.import_file(feeds["checking"], two_checks, None)
    first, second = line("CHECK 1029"), line("CHECK 1030")
    assert bank_queue.similar_lines(first.id)["lines"] == []
    assert next(l for l in bank_queue.list_lines("review")["lines"] if l["id"] == first.id)["anonymous"]
    r = bank_queue.post_line(first.id, {"account_id": chart["6300"], "remember": True})
    assert r["remembered"] is None
    with db.SessionLocal() as session:
        assert session.scalars(select(PayeeRule)).all() == []
    # Posting a check taught history nothing: the next check gets no suggestion.
    assert line("CHECK 1030").suggestion_reason is None and line("CHECK 1030").status == "NEW"


def test_a_check_is_posted_to_the_payee_the_owner_names(chart, feeds):
    revenue = add_payee("Illinois Dept of Revenue", chart["6300"])
    file_import.import_file(feeds["checking"], CHECKING_CSV, None)
    check = line("CHECK 1029")
    bank_queue.post_line(check.id, {"account_id": chart["6300"], "remember": True,
                                    "payee_name": "  illinois dept of REVENUE ", "memo": ""})
    check = line("CHECK 1029")
    with db.SessionLocal() as session:
        entry = session.get(JournalEntry, check.entry_id)
        assert entry.payee_id == revenue
        assert entry.memo == "CHECK 1029 - Illinois Dept of Revenue"
        assert session.scalars(select(PayeeRule)).all() == []
    assert check.description.startswith("CHECK 1029")                # the bank's text is untouched
    posted = next(l for l in bank_queue.list_lines("posted")["lines"] if l["id"] == check.id)
    assert posted["posted_payee"] == "Illinois Dept of Revenue"


def test_a_check_to_a_new_name_creates_the_payee_and_keeps_the_owners_memo(chart, feeds):
    file_import.import_file(feeds["checking"], CHECKING_CSV, None)
    check = line("CHECK 1029")
    bank_queue.post_line(check.id, {"account_id": chart["6300"], "payee_name": "Village Water Dept",
                                    "memo": "Q3 water"})
    with db.SessionLocal() as session:
        entry = session.get(JournalEntry, line("CHECK 1029").entry_id)
        payee = session.get(Payee, entry.payee_id)
        assert (payee.name, payee.is_vendor, payee.is_active) == ("Village Water Dept", True, True)
        assert entry.memo == "Q3 water"


def _history_entry(chart, when, bank_amount, memo):
    """A QuickBooks-history entry on checking: the bank side is `bank_amount`."""
    with db.SessionLocal.begin() as session:
        journal.post_entry(session, entry_date=when, source="IMPORT", memo=memo, lines=[
            journal.LineInput(chart["1010"], Decimal(bank_amount)),
            journal.LineInput(chart["6300"], -Decimal(bank_amount))])


def test_a_line_already_in_quickbooks_history_is_suggested_for_exclusion(chart, feeds):
    # QuickBooks dated the check two days before Chase posted it (09/18): a duplicate.
    _history_entry(chart, date(2026, 9, 16), "-179.88", "CHECK 1029 Illinois Dept of Revenue")
    # Same amount as the Zelle deposit (09/28) but eight days earlier: not the same money.
    _history_entry(chart, date(2026, 9, 20), "1500.00", "Deposit")
    file_import.import_file(feeds["checking"], CHECKING_CSV, None)

    check, zelle = line("CHECK 1029"), line("Zelle payment")
    assert (check.suggestion_reason, check.status) == ("IN_HISTORY", "SUGGESTED")
    assert zelle.suggestion_reason != "IN_HISTORY"
    shown = next(l for l in bank_queue.list_lines("review")["lines"] if l["id"] == check.id)
    assert shown["history_match"]["entry_date"] == "2026-09-16"
    assert shown["history_match"]["memo"] == "CHECK 1029 Illinois Dept of Revenue"

    r = bank_queue.post_suggested(feeds["checking"])
    assert r["excluded"] >= 1
    check = line("CHECK 1029")
    assert (check.status, check.excluded_reason) == ("EXCLUDED", bank_queue.IN_HISTORY_REASON)


def test_one_history_line_covers_only_one_feed_line(chart, feeds):
    two_checks = CHECKING_CSV.replace(
        "Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #\n",
        "Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #\n"
        "CHECK,09/19/2026,\"CHECK 1030  \",-179.88,CHECK_PAID,9000.00,1030,\n", 1)
    _history_entry(chart, date(2026, 9, 16), "-179.88", "CHECK 1029")
    file_import.import_file(feeds["checking"], two_checks, None)
    assert line("CHECK 1029").suggestion_reason == "IN_HISTORY"
    assert line("CHECK 1030").suggestion_reason != "IN_HISTORY"
    # Excluding the first keeps its history line taken: the second is still not a duplicate.
    bank_queue.exclude(line("CHECK 1029").id, bank_queue.IN_HISTORY_REASON)
    assert line("CHECK 1030").suggestion_reason != "IN_HISTORY"


def test_a_rule_the_owner_writes_still_applies_to_a_check(chart, feeds):
    rules.create_rule({"pattern": "CHECK 1029", "match_type": "EQUALS", "account_id": chart["6300"]})
    file_import.import_file(feeds["checking"], CHECKING_CSV, None)
    assert line("CHECK 1029").suggested_account_id == chart["6300"]


# ------------------------------------------------------------------ similar lines

def test_similar_lines_and_post_them_together(chart, feeds):
    file_import.import_file(feeds["card"], CARD_CSV, None)
    coffees = sorted(t["id"] for t in bank_queue.list_lines("review")["lines"] if t["description"] == "COFFEE SHOP")
    similar = bank_queue.similar_lines(coffees[0])
    assert similar["keyword"] == "COFFEE SHOP" and [l["id"] for l in similar["lines"]] == [coffees[1]]
    r = bank_queue.post_with_similar(coffees[0], {"account_id": chart["6300"], "line_ids": [coffees[1]]})
    assert (r["posted"], r["refused"], r["remembered"]["pattern"]) == (2, [], "COFFEE SHOP")
    with db.SessionLocal() as session:
        assert {session.get(BankTxn, i).status for i in coffees} == {"POSTED"}
        assert len(session.scalars(select(PayeeRule)).all()) == 1


def test_post_with_similar_refuses_lines_that_are_not_similar(chart, feeds):
    file_import.import_file(feeds["card"], CARD_CSV, None)
    coffee = line("COFFEE SHOP").id
    with pytest.raises(LedgerError, match="no longer similar"):
        bank_queue.post_with_similar(coffee, {"account_id": chart["6300"], "line_ids": [line("EXAMPLE HOSTING").id]})
    assert line("EXAMPLE HOSTING").status == "NEW"


def test_transfers_are_never_similar(chart, feeds):
    file_import.import_file(feeds["card"], CARD_CSV, None)
    later = CARD_CSV.replace("Memo\n", "Memo\n09/29/2026,09/29/2026,Payment Thank You-Mobile,,Payment,50.00,\n", 1)
    file_import.import_file(feeds["card"], later, None)
    assert bank_queue.similar_lines(line("Payment Thank You").id)["lines"] == []


def test_similar_api(signed_in, chart, feeds):
    signed_in.post("/api/banking/import", json={"bank_account_id": feeds["card"], "content": CARD_CSV})
    coffee = line("COFFEE SHOP").id
    data = signed_in.get(f"/api/banking/lines/{coffee}/similar").get_json()
    assert data["success"] and len(data["lines"]) == 1
    r = signed_in.post(f"/api/banking/lines/{coffee}/post-with-similar",
                       json={"account_id": chart["6300"], "line_ids": [data["lines"][0]["id"]]}).get_json()
    assert r["posted"] == 2


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
