"""
General Ledger v0.6.1
File: utils/migration/rebuild.py
Description: Rebuild the books from QuickBooks and Chase exports, in one command:
             chart, payees, invoice history and journal history up to a boundary date,
             then the Chase feed from that date on. Posted entries are immutable, so a
             re-run is a rebuild, not an update (owner's decision, 2026-09-30).

What the owner has taught the ledger survives it ("learning"): payee rules, edits to
payees (default account, archived, new payees) and the settings QuickBooks does not
carry. It is saved by account NUMBER and payee NAME -- database ids do not survive a
rebuild -- written to a JSON file first as a backup, and restored at the end.

The feed starts at the boundary, so anything QuickBooks has not been given by then never
reaches this ledger. The rebuild therefore compares each Chase file's last GAP_CHECK_DAYS
before the boundary with the history on that account, both ways, and reports what does
not match (the Q3 rehearsal found an unaccepted Zelle deposit, two card charges and a
payment entered twice). It reports; fixing is done in QuickBooks and the rebuild re-run.

Resetting an existing database is for development only: it refuses anything but a
local database. Production is rebuilt into a fresh, empty database.
"""

import json
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select, text

import config
import db
from models import Account, BankAccount, JournalEntry, JournalLine, Payee, PayeeRule, Settings
from utils import bank_accounts, suggest
from utils.errors import LedgerError
from utils.feeds import file_import
from utils.migration import qbo_chart, qbo_invoices, qbo_journal, qbo_payees
from utils.migration.qbo_payees import _key

QBO_FILES = {
    "accounts": "Account List.csv",
    "vendors": "Vendor Contact List.csv",
    "transactions": "Transaction Detail by Account.csv",
    "sales": "Sales by Product_Service Detail.csv",
    "payments": "Invoices and Received Payments.csv",
    "open": "Open Invoices Report.csv",
    "customers": "Customer Contact List.csv",
    "journal": "Journal.csv",
}
SETTINGS_KEPT = ("company_name", "company_address", "fiscal_year_start_month", "zelle_recipient",
                 "zelle_display_name", "invoice_prefix")
# Every table the rebuild owns, children first. alembic_version and settings stay.
GAP_CHECK_DAYS = 90
# QuickBooks dates a bank line by the transaction; Chase by posting, up to a few days later.
GAP_EARLIER, GAP_LATER = timedelta(days=6), timedelta(days=3)
RESET_TABLES = ("invoice_payment", "invoice_line", "invoice", "attachment", "bank_txn", "payee_rule",
                "bank_account", "bank_connection", "journal_line", "journal_entry", "audit_log", "payee", "account")


def find_qbo_files(folder: Path) -> dict[str, Path]:
    """QuickBooks names exports "<Company>_<Report>.csv"; match on the report part."""
    found = {}
    for key, suffix in QBO_FILES.items():
        hits = sorted(folder.glob(f"*{suffix}"))
        if not hits:
            raise LedgerError(f"No QuickBooks export ending in {suffix!r} in {folder}.")
        found[key] = hits[-1]
    return found


# ---------------------------------------------------------------- learning

def save_learning() -> dict:
    with db.SessionLocal() as session:
        numbers = {a.id: a.number for a in session.scalars(select(Account))}
        payees = {p.id: p for p in session.scalars(select(Payee))}
        banks = dict(session.execute(select(BankAccount.id, BankAccount.name)).all())
        settings = session.get(Settings, 1)
        income = session.get(Account, settings.default_income_account_id) if settings.default_income_account_id else None
        return {
            "rules": [{
                "priority": r.priority, "match_field": r.match_field, "match_type": r.match_type,
                "pattern": r.pattern, "bank_account": banks.get(r.bank_account_id),
                "amount_min": str(r.amount_min) if r.amount_min is not None else None,
                "amount_max": str(r.amount_max) if r.amount_max is not None else None,
                "payee": payees[r.payee_id].name if r.payee_id else None,
                "account": numbers.get(r.account_id), "action": r.action,
                "memo_template": r.memo_template, "times_applied": r.times_applied, "is_active": r.is_active,
            } for r in session.scalars(select(PayeeRule))],
            "payees": [{
                "name": p.name, "is_vendor": p.is_vendor, "is_customer": p.is_customer, "email": p.email,
                "address": p.address, "default_account": numbers.get(p.default_account_id),
                "is_1099_vendor": p.is_1099_vendor, "payment_terms_days": p.payment_terms_days,
                "is_active": p.is_active,
            } for p in payees.values()],
            "settings": {**{k: getattr(settings, k) for k in SETTINGS_KEPT},
                         "default_income_account": income.number if income else None},
        }


def restore_learning(learning: dict) -> dict:
    """Put the owner's rules, payee edits and settings back on the rebuilt books. Anything
    that no longer resolves (an account number gone) is reported, not guessed."""
    unresolved = []
    with db.SessionLocal.begin() as session:
        accounts = {a.number: a.id for a in session.scalars(select(Account))}
        payees = {_key(p.name): p for p in session.scalars(select(Payee))}
        banks = {b.name: b.id for b in session.scalars(select(BankAccount))}

        restored_payees = 0
        for saved in learning.get("payees", []):
            p = payees.get(_key(saved["name"]))
            if p is None:
                p = Payee(name=saved["name"])
                session.add(p)
                payees[_key(saved["name"])] = p
            for k in ("is_vendor", "is_customer", "email", "address", "is_1099_vendor", "payment_terms_days", "is_active"):
                setattr(p, k, saved[k])
            if saved["default_account"]:
                if saved["default_account"] in accounts:
                    p.default_account_id = accounts[saved["default_account"]]
                else:
                    unresolved.append(f"payee {saved['name']}: account {saved['default_account']}")
            else:
                p.default_account_id = None
            restored_payees += 1
        session.flush()

        restored_rules = 0
        for r in learning.get("rules", []):
            account = accounts.get(r["account"]) if r["account"] else None
            if r["account"] and account is None:
                unresolved.append(f"rule {r['pattern']!r}: account {r['account']}")
                continue
            session.add(PayeeRule(
                priority=r["priority"], match_field=r["match_field"], match_type=r["match_type"], pattern=r["pattern"],
                bank_account_id=banks.get(r["bank_account"]) if r["bank_account"] else None,
                amount_min=r["amount_min"], amount_max=r["amount_max"],
                payee_id=payees[_key(r["payee"])].id if r["payee"] and _key(r["payee"]) in payees else None,
                account_id=account, action=r["action"], memo_template=r["memo_template"],
                times_applied=r["times_applied"], is_active=r["is_active"]))
            restored_rules += 1

        settings = session.get(Settings, 1)
        saved = learning.get("settings", {})
        for k in SETTINGS_KEPT:
            if k in saved and saved[k] is not None:
                setattr(settings, k, saved[k])
        if saved.get("default_income_account") in accounts:
            settings.default_income_account_id = accounts[saved["default_income_account"]]
        session.flush()
        suggestions = suggest.run(session)
    return {"payees": restored_payees, "rules": restored_rules, "unresolved": unresolved, "suggestions": suggestions}


# ---------------------------------------------------------------- reset (development only)

def reset_dev_database() -> None:
    """Empty every table the rebuild owns, keeping the owner login. Local databases only:
    TRUNCATE is the one way past the immutability triggers, which is exactly why this
    must never reach the production books."""
    url = urlsplit(config.DATABASE_URL.replace("mysql+pymysql", "mysql"))
    if url.hostname not in ("127.0.0.1", "localhost", "db") or (url.hostname == "db" and config.APP_HTTPS):
        raise LedgerError(f"Refusing to reset {url.hostname}: only a local development database is ever reset. "
                          "Rebuild production into a fresh, empty database instead.")
    with db.engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in RESET_TABLES:
            conn.execute(text(f"TRUNCATE TABLE {table}"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        conn.execute(text("UPDATE settings SET lock_date = NULL, next_invoice_seq = 1, default_income_account_id = NULL "
                          "WHERE id = 1"))


# ---------------------------------------------------------------- the boundary check

def history_gaps(session, gl_account_id: int, content: str, before: date,
                 days: int = GAP_CHECK_DAYS) -> dict:
    """Chase lines in the `days` before `before` with no QuickBooks history line on the
    same account (same amount, dated up to six days earlier or three later), and history
    lines on the account in that span that no Chase line accounts for. Closest date first;
    each line pairs once."""
    start = before - timedelta(days=days)
    rows = [r for r in file_import.parse(content).rows if start <= r.posted_date < before]
    if not rows:
        return {"checked_from": start.isoformat(), "not_in_history": [], "not_in_chase": []}
    first = min(r.posted_date for r in rows)
    history = [list(h) + [False] for h in session.execute(
        select(JournalEntry.entry_date, JournalLine.amount, JournalEntry.memo)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(JournalLine.account_id == gl_account_id, JournalEntry.source == "IMPORT",
               JournalEntry.entry_date >= first - GAP_EARLIER, JournalEntry.entry_date < before)
        .order_by(JournalEntry.entry_date, JournalLine.id))]
    not_in_history = []
    for r in sorted(rows, key=lambda r: (r.posted_date, r.row_no)):
        same = [h for h in history if not h[3] and h[1] == r.amount
                and -GAP_LATER <= r.posted_date - h[0] <= GAP_EARLIER]
        if same:
            min(same, key=lambda h: abs(r.posted_date - h[0]))[3] = True
        else:
            not_in_history.append({"date": r.posted_date.isoformat(), "amount": str(r.amount),
                                   "description": r.description[:80]})
    not_in_chase = [{"date": h[0].isoformat(), "amount": str(h[1]), "memo": (h[2] or "")[:80]}
                    for h in history if not h[3] and h[0] >= first]
    return {"checked_from": first.isoformat(), "not_in_history": not_in_history, "not_in_chase": not_in_chase}


# ---------------------------------------------------------------- the rebuild

def rebuild(qbo_dir: Path, before: date, feeds: list[tuple[Path, str, str | None]], *,
            learning: dict | None, active_since: date, log=print) -> dict:
    files = find_qbo_files(qbo_dir)
    read = lambda key: files[key].read_text(encoding="utf-8-sig")  # noqa: E731

    log("1/6 chart of accounts")
    qbo_chart.apply(read("accounts"))
    log("2/6 payees")
    qbo_payees.apply(read("vendors"), read("transactions"), active_since)
    log("3/6 invoice history")
    qbo_invoices.apply(read("sales"), read("payments"), read("open"), read("customers"),
                       active_since=active_since, before=before)
    log("4/6 journal history (a minute or so)")
    history = qbo_journal.apply(read("journal"), before)

    log("5/6 Chase feed")
    with db.SessionLocal() as session:
        numbers = {a.number: a for a in session.scalars(select(Account))}
    imported = []
    for path, number, mask in feeds:
        account = numbers.get(number)
        if account is None:
            raise LedgerError(f"No account {number} for the feed file {path.name}.")
        ba = bank_accounts.create_file_account({"gl_account_id": account.id, "name": account.name, "mask": mask,
                                                "feed_start_date": before.isoformat()})["id"]
        content = path.read_text(encoding="utf-8")
        result = file_import.import_file(ba, content, path.name)
        with db.SessionLocal() as session:
            gaps = history_gaps(session, account.id, content, before)
        imported.append({"file": path.name, "account": f"{number} {account.name}", "lines": result["new"],
                         "gaps": gaps})

    restored = None
    if learning:
        log("6/6 restoring rules, payee edits and settings")
        restored = restore_learning(learning)
    return {"before": before.isoformat(), "history": history, "feeds": imported, "learning": restored}

""" EOF - rebuild.py """
