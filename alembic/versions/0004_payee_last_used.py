"""payee.last_used_on: when a payee was last on a posting.

General Ledger v0.3.3
File: alembic/versions/0004_payee_last_used.py
Description: Lets long-unused payees be archived (is_active = FALSE) without losing them:
             the QuickBooks import fills it from history, and posting keeps it current.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payee", sa.Column("last_used_on", sa.Date, nullable=True))
    op.create_index("ix_payee_active_name", "payee", ["is_active", "name"])


def downgrade() -> None:
    op.drop_index("ix_payee_active_name", "payee")
    op.drop_column("payee", "last_used_on")

""" EOF - 0004_payee_last_used.py """
