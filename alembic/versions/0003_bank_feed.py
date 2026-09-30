"""Bank feed staging: connections, bank accounts, bank lines.

General Ledger v0.3.0
File: alembic/versions/0003_bank_feed.py
Description: Phase 2a (docs/DESIGN.md sections 4 and 5). bank_connection, bank_account
             and bank_txn -- the review queue's staging rows. The suggestion columns
             that point at payee_rule and invoice get their foreign keys when those
             tables exist (phases 2b and 5).

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TABLE_ARGS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}
SOURCES = ("PLAID", "SIMPLEFIN", "FILE")


def upgrade() -> None:
    op.create_table(
        "bank_connection",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("provider", sa.Enum(*SOURCES), nullable=False),
        sa.Column("institution", sa.String(100), nullable=False),
        # The NAME of the access token (docs/CREDENTIALS.md), never the token.
        sa.Column("credential_ref", sa.String(60), nullable=True),
        sa.Column("provider_item_id", sa.String(100), nullable=True),
        sa.Column("sync_cursor", sa.Text, nullable=True),
        sa.Column("status", sa.Enum("OK", "LOGIN_REQUIRED", "ERROR", "DISCONNECTED"),
                  nullable=False, server_default="OK"),
        sa.Column("status_detail", sa.String(255), nullable=True),
        sa.Column("consent_expires_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("last_synced_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("sync_requested_at", mysql.DATETIME(fsp=6), nullable=True),
        **TABLE_ARGS,
    )

    op.create_table(
        "bank_account",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("connection_id", sa.Integer, sa.ForeignKey("bank_connection.id"), nullable=False),
        sa.Column("gl_account_id", sa.Integer, sa.ForeignKey("account.id"), nullable=False),
        sa.Column("provider_account_id", sa.String(100), nullable=True),
        sa.Column("kind", sa.Enum("DEPOSITORY", "CREDIT"), nullable=False),
        sa.Column("mask", sa.String(8), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        # Lines before this are ignored, never queued (DESIGN.md section 10).
        sa.Column("feed_start_date", sa.Date, nullable=False),
        sa.Column("reported_balance", sa.Numeric(14, 2), nullable=True),
        sa.Column("reported_balance_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.UniqueConstraint("gl_account_id", name="uq_gl_account"),
        **TABLE_ARGS,
    )

    op.create_table(
        "bank_txn",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("bank_account_id", sa.Integer, sa.ForeignKey("bank_account.id"), nullable=False),
        sa.Column("source", sa.Enum(*SOURCES), nullable=False),
        # Provider id, or for a CSV row a hash of its content (DESIGN.md section 5.5).
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("posted_date", sa.Date, nullable=False),
        # GL sign for the bank's own GL account: + debits it (DESIGN.md section 5.4).
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("merchant_name", sa.String(120), nullable=True),
        sa.Column("provider_category", sa.String(120), nullable=True),
        sa.Column("status", sa.Enum("NEW", "SUGGESTED", "POSTED", "EXCLUDED", "REMOVED"),
                  nullable=False, server_default="NEW"),
        sa.Column("suggested_account_id", sa.Integer, sa.ForeignKey("account.id"), nullable=True),
        sa.Column("suggested_payee_id", sa.Integer, sa.ForeignKey("payee.id"), nullable=True),
        sa.Column("suggested_rule_id", sa.Integer, nullable=True),
        sa.Column("suggested_invoice_id", sa.Integer, nullable=True),
        sa.Column("suggested_transfer_txn_id", sa.BigInteger, sa.ForeignKey("bank_txn.id"), nullable=True),
        sa.Column("entry_id", sa.BigInteger, sa.ForeignKey("journal_entry.id"), nullable=True),
        sa.Column("excluded_reason", sa.String(120), nullable=True),
        # As received: record first, interpret later.
        sa.Column("raw_json", sa.JSON, nullable=False),
        sa.Column("first_seen_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint("bank_account_id", "source", "external_id", name="uq_bank_txn"),
        sa.Index("ix_bank_txn_status", "status", "posted_date"),
        **TABLE_ARGS,
    )


def downgrade() -> None:
    op.drop_table("bank_txn")
    op.drop_table("bank_account")
    op.drop_table("bank_connection")

""" EOF - 0003_bank_feed.py """
