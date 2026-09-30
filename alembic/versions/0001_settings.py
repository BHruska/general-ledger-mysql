"""Settings row with the owner login columns.

General Ledger v0.1.0
File: alembic/versions/0001_settings.py
Description: Phase 0. The login half of docs/DESIGN.md section 4's `settings`; phase 1
             adds the account columns once the chart of accounts exists.

Revision ID: 0001
Revises:
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    settings = op.create_table(
        "settings",
        sa.Column("id", sa.SmallInteger, primary_key=True, autoincrement=False),
        sa.Column("company_name", sa.String(120), nullable=False, server_default=""),
        # NULL until `manage.py set-password`; login refuses while it is NULL.
        sa.Column("owner_password_hash", sa.String(255), nullable=True),
        sa.Column("totp_secret_ref", sa.String(60), nullable=True),
        # The table holds exactly one row. This makes a second one impossible rather
        # than merely unexpected.
        sa.CheckConstraint("id = 1", name="ck_settings_single_row"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.bulk_insert(settings, [{"id": 1, "company_name": ""}])


def downgrade() -> None:
    op.drop_table("settings")

""" EOF - 0001_settings.py """
