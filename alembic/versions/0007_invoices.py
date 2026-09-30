"""Invoices, invoice lines, invoice payments, and the invoice settings.

General Ledger v0.5.0
File: alembic/versions/0007_invoices.py
Description: docs/DESIGN.md sections 4 and 8, brought ahead of phase 3 by the owner's
             decision (2026-09-30) because invoices are frequent enough to matter and
             their history is wanted.

Differences from DESIGN.md section 4, each because QuickBooks history has to fit:
  - invoice.source (LEDGER | QBO) and invoice.paid_on: history comes from QuickBooks
    and never posts; paid_on is when the last payment completed it.
  - invoice_payment.entry_id is nullable, with paid_on and source: a QuickBooks payment
    has no journal entry here (its income reached the books through QuickBooks, and
    reaches this ledger once, through the opening balances), and QuickBooks does not say
    which invoice a payment paid, so history allocations are derived oldest-first and
    marked source = 'QBO_DERIVED'.
  - settings.invoice_prefix defaults to '' and the sequence continues QuickBooks' own
    numbers (owner's decision), instead of DESIGN's INV-yyyy-nnnn.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TABLE_ARGS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}
MONEY = sa.Numeric(14, 2)


def upgrade() -> None:
    op.create_table(
        "invoice",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("number", sa.String(20), nullable=False),
        sa.Column("customer_id", sa.Integer, sa.ForeignKey("payee.id"), nullable=False),
        sa.Column("issue_date", sa.Date, nullable=False),
        sa.Column("due_date", sa.Date, nullable=False),
        sa.Column("terms", sa.String(40), nullable=True),
        sa.Column("status", sa.Enum("DRAFT", "OPEN", "PAID", "VOID"), nullable=False, server_default="DRAFT"),
        sa.Column("total", MONEY, nullable=False, server_default="0"),
        # Maintained by utils/invoices.py only, from invoice_payment rows.
        sa.Column("amount_paid", MONEY, nullable=False, server_default="0"),
        sa.Column("paid_on", sa.Date, nullable=True),
        sa.Column("memo", sa.Text, nullable=True),
        sa.Column("source", sa.Enum("LEDGER", "QBO"), nullable=False, server_default="LEDGER"),
        # The Dr A/R / Cr income entry, set on issue. NULL for QuickBooks history.
        sa.Column("entry_id", sa.BigInteger, sa.ForeignKey("journal_entry.id"), nullable=True),
        sa.Column("pdf_path", sa.String(255), nullable=True),
        sa.Column("email_requested_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("emailed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.UniqueConstraint("number", name="uq_invoice_number"),
        sa.Index("ix_invoice_customer", "customer_id", "issue_date"),
        sa.Index("ix_invoice_status", "status", "due_date"),
        **TABLE_ARGS,
    )
    op.create_table(
        "invoice_line",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("invoice_id", sa.Integer, sa.ForeignKey("invoice.id"), nullable=False),
        sa.Column("line_no", sa.SmallInteger, nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("quantity", sa.Numeric(10, 2), nullable=False, server_default="1"),
        sa.Column("rate", MONEY, nullable=False),
        # quantity x rate, rounded half-up, computed by the server.
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("income_account_id", sa.Integer, sa.ForeignKey("account.id"), nullable=False),
        sa.UniqueConstraint("invoice_id", "line_no", name="uq_invoice_line"),
        **TABLE_ARGS,
    )
    op.create_table(
        "invoice_payment",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("invoice_id", sa.Integer, sa.ForeignKey("invoice.id"), nullable=False),
        sa.Column("entry_id", sa.BigInteger, sa.ForeignKey("journal_entry.id"), nullable=True),
        sa.Column("paid_on", sa.Date, nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("source", sa.Enum("LEDGER", "QBO_DERIVED"), nullable=False, server_default="LEDGER"),
        sa.Index("ix_invoice_payment_invoice", "invoice_id"),
        **TABLE_ARGS,
    )
    op.add_column("settings", sa.Column("invoice_prefix", sa.String(10), nullable=False, server_default=""))
    op.add_column("settings", sa.Column("next_invoice_seq", sa.Integer, nullable=False, server_default="1"))
    op.add_column("settings", sa.Column("zelle_recipient", sa.String(120), nullable=True))
    op.add_column("settings", sa.Column("zelle_display_name", sa.String(120), nullable=True))
    op.add_column("settings", sa.Column("default_income_account_id", sa.Integer,
                                        sa.ForeignKey("account.id", name="fk_settings_income_account"),
                                        nullable=True))


def downgrade() -> None:
    op.drop_constraint("fk_settings_income_account", "settings", type_="foreignkey")
    for column in ("default_income_account_id", "zelle_display_name", "zelle_recipient",
                   "next_invoice_seq", "invoice_prefix"):
        op.drop_column("settings", column)
    op.drop_table("invoice_payment")
    op.drop_table("invoice_line")
    op.drop_table("invoice")

""" EOF - 0007_invoices.py """
