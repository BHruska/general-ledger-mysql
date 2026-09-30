"""Drafts have no number yet; bank lines can point at the invoice they pay.

General Ledger v0.5.1
File: alembic/versions/0008_invoice_drafts.py
Description: Invoicing step B (docs/DESIGN.md section 8). A number is assigned only on
             issue, so the sequence never skips or reuses one (8.1); a draft's number is
             NULL (a unique key allows many NULLs). bank_txn.suggested_invoice_id gets the
             foreign key it has waited for since migration 0003.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("invoice", "number", existing_type=sa.String(20), nullable=True)
    op.create_foreign_key("fk_bank_txn_invoice", "bank_txn", "invoice", ["suggested_invoice_id"], ["id"],
                          ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_bank_txn_invoice", "bank_txn", type_="foreignkey")
    op.alter_column("invoice", "number", existing_type=sa.String(20), nullable=False)

""" EOF - 0008_invoice_drafts.py """
