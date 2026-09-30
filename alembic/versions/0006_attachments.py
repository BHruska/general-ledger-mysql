"""attachment: receipts on a bank line or a journal entry.

General Ledger v0.4.1
File: alembic/versions/0006_attachments.py
Description: docs/DESIGN.md section 4, attachment. The file lives under /data (backed up
             nightly, as business records should be); the row records where, its SHA-256
             and what it is attached to.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attachment",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("entry_id", sa.BigInteger, sa.ForeignKey("journal_entry.id"), nullable=True),
        # A receipt can be attached before the line is posted; posting carries it to the entry.
        sa.Column("bank_txn_id", sa.BigInteger, sa.ForeignKey("bank_txn.id"), nullable=True),
        sa.Column("filename", sa.String(255), nullable=False),
        # Relative to /data: attachments/yyyy/mm/<sha256>.<ext>
        sa.Column("stored_path", sa.String(255), nullable=False),
        sa.Column("sha256", sa.CHAR(64), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("uploaded_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Index("ix_attachment_entry", "entry_id"),
        sa.Index("ix_attachment_bank_txn", "bank_txn_id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )


def downgrade() -> None:
    op.drop_table("attachment")

""" EOF - 0006_attachments.py """
