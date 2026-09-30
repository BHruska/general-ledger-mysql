"""
General Ledger v0.3.0
File: models.py
Description: ORM models for docs/DESIGN.md section 4. Phase 1: settings, account,
             payee, journal_entry, journal_line, audit_log. Phase 2a: bank_connection,
             bank_account, bank_txn.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (JSON, BigInteger, Boolean, Date, Enum, ForeignKey, Integer, Numeric,
                        SmallInteger, String, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base, utc_timestamp

ACCOUNT_TYPES = ("ASSET", "LIABILITY", "EQUITY", "INCOME", "EXPENSE")
ENTRY_SOURCES = ("MANUAL", "BANK", "INVOICE", "PAYMENT", "OPENING", "REVERSAL", "IMPORT")

# DESIGN.md section 3.1: an account's balance in its normal direction is
# SUM(amount) x normal_sign. This is the only place that sign lives.
NORMAL_SIGN = {"ASSET": 1, "EXPENSE": 1, "LIABILITY": -1, "EQUITY": -1, "INCOME": -1}

# DESIGN.md section 3.3: account numbers fall in the range of their type.
NUMBER_RANGES = {
    "ASSET": (1000, 1999),
    "LIABILITY": (2000, 2999),
    "EQUITY": (3000, 3999),
    "INCOME": (4000, 4999),
    "EXPENSE": (5000, 7999),
}


class Settings(Base):
    """The one-row settings table (id is always 1).

    owner_password_hash is nullable, unlike DESIGN.md section 4, because the row exists
    before anyone has chosen a password; login refuses while it is NULL. The invoicing
    and 1099 columns arrive with phase 5.
    """

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    company_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    company_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    fiscal_year_start_month: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    lock_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    ar_account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), nullable=False)
    retained_earnings_account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), nullable=False)
    owner_password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # A credential_ref, never the TOTP secret itself (docs/CREDENTIALS.md section 4).
    totp_secret_ref: Mapped[str | None] = mapped_column(String(60), nullable=True)
    invoice_prefix: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    next_invoice_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    zelle_recipient: Mapped[str | None] = mapped_column(String(120), nullable=True)
    zelle_display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    default_income_account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"), nullable=True)


class Account(Base):
    __tablename__ = "account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(Enum(*ACCOUNT_TYPES), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_bank_account: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tax_line: Mapped[str | None] = mapped_column(String(60), nullable=True)
    is_1099_expense: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    @property
    def normal_sign(self) -> int:
        return NORMAL_SIGN[self.type]


class Payee(Base):
    """Vendors and customers share one table. Inactive payees are kept but hidden."""

    __tablename__ = "payee"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    is_customer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_vendor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"), nullable=True)
    is_1099_vendor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tax_id_ref: Mapped[str | None] = mapped_column(String(60), nullable=True)
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # When this payee was last on a posting; archiving keys off it.
    last_used_on: Mapped[date | None] = mapped_column(Date, nullable=True)


class JournalEntry(Base):
    __tablename__ = "journal_entry"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    memo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(Enum(*ENTRY_SOURCES), nullable=False)
    payee_id: Mapped[int | None] = mapped_column(ForeignKey("payee.id"), nullable=True)
    reverses_entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entry.id"), nullable=True)
    reversed_by_entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entry.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(utc_timestamp(), nullable=False)

    lines: Mapped[list["JournalLine"]] = relationship(
        back_populates="entry", order_by="JournalLine.line_no", lazy="selectin"
    )


class JournalLine(Base):
    __tablename__ = "journal_line"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entry.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), nullable=False)
    # Debit positive, credit negative; never 0 (DESIGN.md section 3.1).
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    memo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cleared_recon_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    entry: Mapped[JournalEntry] = relationship(back_populates="lines")


FEED_SOURCES = ("PLAID", "SIMPLEFIN", "FILE")
BANK_TXN_STATUSES = ("NEW", "SUGGESTED", "POSTED", "EXCLUDED", "REMOVED")


class BankConnection(Base):
    """One Plaid Item, one SimpleFIN access URL, or the FILE pseudo-connection."""

    __tablename__ = "bank_connection"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(Enum(*FEED_SOURCES), nullable=False)
    institution: Mapped[str] = mapped_column(String(100), nullable=False)
    credential_ref: Mapped[str | None] = mapped_column(String(60), nullable=True)
    provider_item_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sync_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("OK", "LOGIN_REQUIRED", "ERROR", "DISCONNECTED"), nullable=False, default="OK")
    status_detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    consent_expires_at: Mapped[datetime | None] = mapped_column(utc_timestamp(), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(utc_timestamp(), nullable=True)
    sync_requested_at: Mapped[datetime | None] = mapped_column(utc_timestamp(), nullable=True)


class BankAccount(Base):
    """One feed account = one GL bank account."""

    __tablename__ = "bank_account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("bank_connection.id"), nullable=False)
    gl_account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), nullable=False, unique=True)
    provider_account_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    kind: Mapped[str] = mapped_column(Enum("DEPOSITORY", "CREDIT"), nullable=False)
    mask: Mapped[str | None] = mapped_column(String(8), nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    feed_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    reported_balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    reported_balance_at: Mapped[datetime | None] = mapped_column(utc_timestamp(), nullable=True)


class BankTxn(Base):
    """A bank line awaiting review (DESIGN.md section 6). Only a human posts or excludes."""

    __tablename__ = "bank_txn"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    bank_account_id: Mapped[int] = mapped_column(ForeignKey("bank_account.id"), nullable=False)
    source: Mapped[str] = mapped_column(Enum(*FEED_SOURCES), nullable=False)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    posted_date: Mapped[date] = mapped_column(Date, nullable=False)
    # GL sign for the bank's own GL account: + debits it (DESIGN.md section 5.4).
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    merchant_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(Enum(*BANK_TXN_STATUSES), nullable=False, default="NEW")
    suggested_account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"), nullable=True)
    suggested_payee_id: Mapped[int | None] = mapped_column(ForeignKey("payee.id"), nullable=True)
    suggested_rule_id: Mapped[int | None] = mapped_column(ForeignKey("payee_rule.id"), nullable=True)
    suggested_invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoice.id"), nullable=True)
    suggested_transfer_txn_id: Mapped[int | None] = mapped_column(ForeignKey("bank_txn.id"), nullable=True)
    # Where the suggestion came from: RULE, RULE_EXCLUDE, PAYEE, HISTORY, TRANSFER,
    # TRANSFER_WAITING (a card payment whose other side has not arrived yet).
    suggestion_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entry.id"), nullable=True)
    excluded_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(utc_timestamp(), nullable=False)


class PayeeRule(Base):
    """"Description contains X -> account Y" (DESIGN.md section 6.4). Suggests; never posts."""

    __tablename__ = "payee_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    match_field: Mapped[str] = mapped_column(Enum("DESCRIPTION", "MERCHANT"), nullable=False, default="DESCRIPTION")
    match_type: Mapped[str] = mapped_column(
        Enum("CONTAINS", "STARTS_WITH", "EQUALS", "REGEX"), nullable=False, default="CONTAINS")
    pattern: Mapped[str] = mapped_column(String(200), nullable=False)
    bank_account_id: Mapped[int | None] = mapped_column(ForeignKey("bank_account.id"), nullable=True)
    amount_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    amount_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    payee_id: Mapped[int | None] = mapped_column(ForeignKey("payee.id"), nullable=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"), nullable=True)
    action: Mapped[str] = mapped_column(Enum("SUGGEST", "EXCLUDE", "TRANSFER"), nullable=False, default="SUGGEST")
    memo_template: Mapped[str | None] = mapped_column(String(255), nullable=True)
    times_applied: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Attachment(Base):
    """A receipt or document on a bank line and/or the entry that posted it."""

    __tablename__ = "attachment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entry.id"), nullable=True)
    bank_txn_id: Mapped[int | None] = mapped_column(ForeignKey("bank_txn.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(utc_timestamp(), nullable=False)


INVOICE_STATUSES = ("DRAFT", "OPEN", "PAID", "VOID")


class Invoice(Base):
    __tablename__ = "invoice"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Assigned on issue; a draft has none, so the sequence never skips or reuses a number.
    number: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("payee.id"), nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    terms: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(Enum(*INVOICE_STATUSES), nullable=False, default="DRAFT")
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Enum("LEDGER", "QBO"), nullable=False, default="LEDGER")
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entry.id"), nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_requested_at: Mapped[datetime | None] = mapped_column(utc_timestamp(), nullable=True)
    emailed_at: Mapped[datetime | None] = mapped_column(utc_timestamp(), nullable=True)

    lines: Mapped[list["InvoiceLine"]] = relationship(order_by="InvoiceLine.line_no", lazy="selectin")
    payments: Mapped[list["InvoicePayment"]] = relationship(order_by="InvoicePayment.paid_on", lazy="selectin")

    @property
    def balance(self) -> Decimal:
        return self.total - self.amount_paid


class InvoiceLine(Base):
    __tablename__ = "invoice_line"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoice.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=1)
    rate: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    income_account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), nullable=False)


class InvoicePayment(Base):
    """Links a receipt to the invoice it pays. QBO_DERIVED rows are history allocated
    oldest-first from QuickBooks' payment list, with no entry here."""

    __tablename__ = "invoice_payment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoice.id"), nullable=False)
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entry.id"), nullable=True)
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    source: Mapped[str] = mapped_column(Enum("LEDGER", "QBO_DERIVED"), nullable=False, default="LEDGER")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[datetime] = mapped_column(utc_timestamp(), nullable=False)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    object_type: Mapped[str] = mapped_column(String(40), nullable=False)
    object_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)

""" EOF - models.py """
