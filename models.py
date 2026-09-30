"""
General Ledger v0.2.0
File: models.py
Description: ORM models for docs/DESIGN.md section 4. Phase 1: settings, account,
             payee, journal_entry, journal_line, audit_log.
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
    """Vendors and customers share one table. No UI until phase 2."""

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


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[datetime] = mapped_column(utc_timestamp(), nullable=False)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    object_type: Mapped[str] = mapped_column(String(40), nullable=False)
    object_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)

""" EOF - models.py """
