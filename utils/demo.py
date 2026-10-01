"""
General Ledger v0.7.0
File: utils/demo.py
Description: Fills an empty, migrated database with a made-up company's last three months,
             so every part of the app has something real to show
             (`python manage.py make-demo`).

Everything goes through the app's own code paths, exactly as the owner would use them:
customers and invoices are created and issued; the bank's activity arrives as Chase-style
CSV downloads through the importer; lines are posted by accepting suggestions or choosing
an account with "Remember" (which writes the rules later lines are suggested by); card
payments pair into one transfer; deposits pay invoices. What is left shows the rest:

  - the last DAYS_IN_REVIEW days wait in Banking -> Review, most already suggested;
  - one invoice is overdue, the latest are open, and one is still a draft;
  - the first month is locked.

Dates are relative to today, so a demo book is always current. Amounts are fixed (no
randomness), so two demo books made on the same day are identical.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

import db
from models import Account, BankTxn, Payee, Settings
from utils import accounts, bank_accounts, bank_queue, invoices, journal, settings_manager
from utils.errors import LedgerError
from utils.feeds import file_import

log = logging.getLogger(__name__)

D = Decimal
COMPANY = "Bluebird Design Studio LLC"
ADDRESS = "100 Example Avenue, Suite 2\nSpringfield, IL 62701"
OPENING_CASH = D("18000.00")
DAYS_IN_REVIEW = 12
CHECKING_MASK, CARD_MASK = "1234", "5678"

CUSTOMERS = {
    "acme": ("Acme Dental Group", "billing@acmedental.example"),
    "riverside": ("Riverside Bakery", "owner@riversidebakery.example"),
    "harbor": ("Harbor Law Partners", "accounts@harborlaw.example"),
    "summit": ("Summit Fitness", "hello@summitfitness.example"),
}

# Card charges: (day of month, bank text, amount, Chase category, account number). Bank
# text is what a real statement shows, so the suggestions have real work to do.
MONTHLY_CARD = [
    (2, "ADOBE *CREATIVE CLD", "59.99", "Shopping", "6120"),
    (4, "GOOGLE *WORKSPACE BLUEB", "14.40", "Professional Services", "6120"),
    (6, "DIGITALOCEAN.COM", "24.00", "Professional Services", "6110"),
    (9, "VERIZON WIRELESS", "85.00", "Bills & Utilities", "6200"),
    (11, "ZOOM.US 888-799-9666", "15.99", "Professional Services", "6120"),
    (13, "BLUE BOTTLE COFFEE", "18.75", "Food & Drink", "6350"),
    (16, "STAPLES 00123", "46.18", "Office & Shipping", "6400"),
    (19, "PANERA BREAD #4521", "27.40", "Food & Drink", "6350"),
]
ONE_OFF_CARD = {  # month index -> charges
    1: [(8, "UNITED 0162345678901", "412.60", "Travel", "6300"),
        (10, "HILTON HOTELS CHICAGO", "389.12", "Travel", "6300")],
    2: [(5, "FACEBOOK *ADS 7PQ2", "150.00", "Professional Services", "6000"),
        # A vendor never seen before, late in the month: it waits in Review unsuggested,
        # to show choosing an account (and Remember) for something new.
        (26, "CANVA* I0451234567", "12.99", "Professional Services", "6120")],
}
# Checking: (day, text, amount, Chase type, account number); negative is money out.
MONTHLY_CHECKING = [
    (1, "ORIG CO NAME:SUNRISE PROPERTIES ORIG ID:9000000001 DESC DATE: CO ENTRY DESCR:RENT SEC:PPD",
     "-1450.00", "ACH_DEBIT", "6250"),
    (25, "Online Transfer to CHK ...9999 transaction#: 00001", "-2000.00", "ACCT_XFER", "3100"),
    (27, "MONTHLY SERVICE FEE", "-15.00", "FEE_TRANSACTION", "6050"),
]
ONE_OFF_CHECKING = {1: [(14, "CHECK 1001", "-350.00", "CHECK_PAID", "6700")]}

# Invoices: (month index, day issued, customer, [(description, quantity, rate)], paid how).
# "zelle" is paid ~12 days later by Zelle naming the number; "check" by a mobile check
# deposit (no text to match: posted to the invoice by hand); None stays open.
INVOICES = [
    (0, 5, "acme", [("Monthly design retainer", "1", "1500.00")], "zelle"),
    (0, 8, "riverside", [("Menu and signage design", "12", "85.00")], "zelle"),
    (1, 5, "acme", [("Monthly design retainer", "1", "1500.00")], "zelle"),
    (1, 9, "harbor", [("Website redesign - phase 1", "1", "2400.00")], None),  # overdue
    (1, 20, "summit", [("Class schedule poster", "6", "75.00"), ("Print-ready files", "1", "50.00")], "check"),
    (2, 5, "acme", [("Monthly design retainer", "1", "1500.00")], "zelle"),
    (2, 12, "riverside", [("Seasonal menu update", "4.5", "85.00")], "zelle"),
]


@dataclass
class Line:
    on: date
    account: str          # "checking" or "card"
    text: str
    amount: Decimal       # bank sign: negative is money out / a charge
    kind: str             # Chase category (card) or type (checking)
    post_to: str | None   # account number, or None when a suggestion or invoice decides
    invoice: int | None = None


def _months(today: date) -> list[date]:
    first = date(today.year, today.month, 1)
    out = []
    for back in (3, 2, 1):
        y, m = first.year, first.month - back
        while m < 1:
            y, m = y - 1, m + 12
        out.append(date(y, m, 1))
    return out


def _on(month: date, day: int) -> date:
    return month + timedelta(days=day - 1)


# ---------------------------------------------------------------- set-up

def _setup(start: date) -> dict:
    with db.SessionLocal.begin() as session:
        s = session.get(Settings, 1)
        s.company_name, s.company_address = COMPANY, ADDRESS
        s.zelle_recipient, s.zelle_display_name = "pay@bluebird.example", "Bluebird Design Studio"
        s.invoice_prefix, s.next_invoice_seq = "INV-", 1001
        for number, name in (("1010", "Business Checking"), ("2010", "Business Card"), ("4000", "Design Services")):
            session.scalar(select(Account).where(Account.number == number)).name = name
    accounts.create_account({"number": "6250", "name": "Rent", "type": "EXPENSE"})
    ids = {a["number"]: a["id"] for a in accounts.list_accounts()}
    settings_manager.update_company({"default_income_account_id": ids["4000"]})

    with db.SessionLocal.begin() as session:
        journal.post_entry(session, entry_date=start - timedelta(days=1), source="OPENING",
                           memo="Opening balance", lines=[
                               journal.LineInput(ids["1010"], OPENING_CASH),
                               journal.LineInput(ids["3000"], -OPENING_CASH)])
    feeds = {
        "checking": bank_accounts.create_file_account({"gl_account_id": ids["1010"], "name": "Business Checking",
                                                       "mask": CHECKING_MASK, "feed_start_date": start.isoformat(),
                                                       "institution": "Demo Bank"})["id"],
        "card": bank_accounts.create_file_account({"gl_account_id": ids["2010"], "name": "Business Card",
                                                   "mask": CARD_MASK, "feed_start_date": start.isoformat(),
                                                   "institution": "Demo Bank"})["id"],
    }
    return {"ids": ids, "feeds": feeds}


def _customers() -> dict[str, int]:
    out = {}
    for key, (name, email) in CUSTOMERS.items():
        out[key] = invoices.create_customer({"name": name, "email": email})["id"]
    with db.SessionLocal.begin() as session:
        for cid in out.values():
            session.get(Payee, cid).payment_terms_days = 15
    return out


def _invoices(months: list[date], today: date, customers: dict[str, int]) -> list[Line]:
    """Issue the invoices (in date order, so the numbers run in order) and return the
    bank lines that pay them."""
    lines = []
    for month_ix, day, who, rows, paid in sorted(INVOICES, key=lambda i: _on(months[i[0]], i[1])):
        issued = _on(months[month_ix], day)
        if issued >= today:
            continue
        draft = invoices.save_draft({"customer_id": customers[who], "issue_date": issued.isoformat(),
                                     "lines": [{"description": d, "quantity": q, "rate": r} for d, q, r in rows]})
        result = invoices.issue(draft["id"])
        total = sum((D(q) * D(r) for _, q, r in rows), D("0")).quantize(D("0.01"))
        paid_on = issued + timedelta(days=12)
        if paid and paid_on < today:
            name = CUSTOMERS[who][0].upper()
            text = (f"Zelle payment from {name} {result['number']} 9X{draft['id']:04d}"
                    if paid == "zelle" else "REMOTE ONLINE DEPOSIT # 1")
            kind = "PARTNERFI_TO_CHASE" if paid == "zelle" else "CHECK_DEPOSIT"
            lines.append(Line(paid_on, "checking", text, total, kind, None, invoice=draft["id"]))
    # One draft, for next month, to show the editor.
    invoices.save_draft({"customer_id": customers["summit"], "issue_date": today.isoformat(),
                         "lines": [{"description": "Monthly social media graphics", "quantity": "8", "rate": "45.00"}]})
    return lines


def _bank_lines(months: list[date], today: date) -> list[Line]:
    lines = []
    for ix, month in enumerate(months):
        for day, text, amount, kind, post_to in MONTHLY_CARD + ONE_OFF_CARD.get(ix, []):
            lines.append(Line(_on(month, day), "card", text, -D(amount), kind, post_to))
        for day, text, amount, kind, post_to in MONTHLY_CHECKING + ONE_OFF_CHECKING.get(ix, []):
            lines.append(Line(_on(month, day), "checking", text, D(amount), kind, post_to))
    # The card is paid in full on the 21st from checking: one transfer, both sides.
    for month in months[1:] + [None]:
        paid_on = _on(month, 21) if month else None
        if paid_on is None or paid_on >= today:
            break
        owed = -sum((l.amount for l in lines if l.account == "card" and l.on < paid_on and l.amount < 0), D("0"))
        owed -= sum((l.amount for l in lines if l.account == "card" and l.amount > 0), D("0"))
        if owed <= 0:
            continue
        lines.append(Line(paid_on, "card", "AUTOMATIC PAYMENT - THANK", owed, "Payment", None))
        lines.append(Line(paid_on, "checking", f"Payment to Chase card ending in {CARD_MASK} {paid_on:%m/%d}",
                          -owed, "ACCT_XFER", None))
    return [l for l in lines if l.on < today]


# ---------------------------------------------------------------- the bank files

def _card_csv(lines: list[Line]) -> str:
    rows = ["Transaction Date,Post Date,Description,Category,Type,Amount,Memo"]
    for l in sorted(lines, key=lambda l: l.on, reverse=True):
        kind = "Payment" if l.amount > 0 else "Sale"
        category = "" if l.amount > 0 else l.kind
        rows.append(f"{(l.on - timedelta(days=1)):%m/%d/%Y},{l.on:%m/%d/%Y},{l.text},{category},{kind},{l.amount},")
    return "\n".join(rows) + "\n"


def _checking_csv(lines: list[Line]) -> str:
    rows = ["Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #"]
    balance, with_balance = OPENING_CASH, []
    for l in sorted(lines, key=lambda l: (l.on, l.amount)):
        balance += l.amount
        with_balance.append((l, balance))
    for l, bal in reversed(with_balance):
        details = "CHECK" if l.kind == "CHECK_PAID" else ("CREDIT" if l.amount > 0 else "DEBIT")
        slip = l.text.split()[-1] if l.kind == "CHECK_PAID" else ""
        rows.append(f'{details},{l.on:%m/%d/%Y},"{l.text}",{l.amount},{l.kind},{bal},{slip},')
    return "\n".join(rows) + "\n"


# ---------------------------------------------------------------- posting

def _post_older_lines(lines: list[Line], cutoff: date, ids: dict[str, int]) -> None:
    """Post everything before `cutoff` as the owner would: accept a suggestion when there
    is one, otherwise choose the account with Remember (so later lines get suggested),
    and post invoice payments to their invoice."""
    by_text = {(l.on, l.text): l for l in lines}
    while True:
        with db.SessionLocal() as session:
            waiting = session.scalars(select(BankTxn).where(
                BankTxn.status.in_(bank_queue.REVIEWABLE), BankTxn.posted_date < cutoff)
                .order_by(BankTxn.posted_date, BankTxn.id)).all()
        if not waiting:
            return
        txn = waiting[0]
        plan = by_text.get((txn.posted_date, txn.description))
        if txn.status == "SUGGESTED" and txn.suggestion_reason == "TRANSFER":
            data = {}
        elif plan is not None and plan.invoice is not None:
            data = {"invoice_id": plan.invoice}
        elif txn.status == "SUGGESTED" and txn.suggested_account_id:
            data = {"account_id": txn.suggested_account_id}
        elif plan is not None and plan.post_to:
            data = {"account_id": ids[plan.post_to], "remember": True}
        else:
            raise LedgerError(f"The demo has no plan for {txn.posted_date} {txn.description!r}.")
        bank_queue.post_line(txn.id, data)


def populate(today: date | None = None) -> None:
    """Fill the (new, empty) database with the demo company."""
    today = today or date.today()
    months = _months(today)
    start = months[0]
    base = _setup(start)
    customers = _customers()
    lines = _invoices(months, today, customers) + _bank_lines(months, today)

    file_import.import_file(base["feeds"]["card"], _card_csv([l for l in lines if l.account == "card"]),
                            "demo-card.csv")
    file_import.import_file(base["feeds"]["checking"], _checking_csv([l for l in lines if l.account == "checking"]),
                            "demo-checking.csv")
    _post_older_lines(lines, today - timedelta(days=DAYS_IN_REVIEW), base["ids"])
    bank_queue.refresh_suggestions()

    lock = _on(months[1], 1) - timedelta(days=1)  # the end of the first month
    if lock < today:
        settings_manager.set_lock_date({"lock_date": lock.isoformat()})
    log.info("Demo book filled: %s to %s.", start, today)

""" EOF - utils/demo.py """
