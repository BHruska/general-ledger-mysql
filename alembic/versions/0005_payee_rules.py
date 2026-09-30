"""payee_rule, and why a bank line was suggested what it was.

General Ledger v0.4.0
File: alembic/versions/0005_payee_rules.py
Description: Phase 2b (docs/DESIGN.md sections 4 and 6.4). payee_rule as designed, the
             foreign key bank_txn.suggested_rule_id has waited for, and
             bank_txn.suggestion_reason so the review queue can say where a suggestion
             came from.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payee_rule",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        # Lower wins; the first matching rule decides.
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("match_field", sa.Enum("DESCRIPTION", "MERCHANT"), nullable=False, server_default="DESCRIPTION"),
        sa.Column("match_type", sa.Enum("CONTAINS", "STARTS_WITH", "EQUALS", "REGEX"),
                  nullable=False, server_default="CONTAINS"),
        sa.Column("pattern", sa.String(200), nullable=False),
        sa.Column("bank_account_id", sa.Integer, sa.ForeignKey("bank_account.id"), nullable=True),
        sa.Column("amount_min", sa.Numeric(14, 2), nullable=True),
        sa.Column("amount_max", sa.Numeric(14, 2), nullable=True),
        sa.Column("payee_id", sa.Integer, sa.ForeignKey("payee.id"), nullable=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("account.id"), nullable=True),
        sa.Column("action", sa.Enum("SUGGEST", "EXCLUDE", "TRANSFER"), nullable=False, server_default="SUGGEST"),
        sa.Column("memo_template", sa.String(255), nullable=True),
        sa.Column("times_applied", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_foreign_key("fk_bank_txn_rule", "bank_txn", "payee_rule", ["suggested_rule_id"], ["id"],
                          ondelete="SET NULL")
    # RULE, RULE_EXCLUDE, PAYEE, HISTORY, TRANSFER, TRANSFER_WAITING.
    op.add_column("bank_txn", sa.Column("suggestion_reason", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("bank_txn", "suggestion_reason")
    op.drop_constraint("fk_bank_txn_rule", "bank_txn", type_="foreignkey")
    op.drop_table("payee_rule")

""" EOF - 0005_payee_rules.py """
