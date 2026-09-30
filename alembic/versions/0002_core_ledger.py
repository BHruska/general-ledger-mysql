"""Core ledger: chart of accounts, payees, journal, audit log, lock date, triggers.

General Ledger v0.2.0
File: alembic/versions/0002_core_ledger.py
Description: Phase 1 (docs/DESIGN.md sections 3 and 4). Creates account, payee,
             journal_entry, journal_line and audit_log; adds the phase-1 settings
             columns; seeds a small default chart; and installs the section 3.2a
             triggers that keep posted lines immutable even outside the app.

The seed chart has no tax_line mapping yet: that depends on the entity type
(DESIGN.md section 14, question 4), and the QuickBooks import replaces this chart anyway.

The triggers need log_bin_trust_function_creators=1 on the server (compose.dev.yml sets
it for dev). If the infra side declines, drop the TRIGGERS list below and nothing else
changes: utils/journal.py enforces every rule first regardless.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLE_ARGS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}
MONEY = sa.Numeric(14, 2)

# number, name, type, parent number, is_bank_account, is_1099_expense
SEED_CHART = [
    ("1010", "Chase Checking", "ASSET", None, True, False),
    ("1200", "Accounts Receivable", "ASSET", None, False, False),
    ("2010", "Chase Ink Card", "LIABILITY", None, True, False),
    ("2200", "Owner Loan", "LIABILITY", None, False, False),
    ("3000", "Owner's Equity", "EQUITY", None, False, False),
    ("3100", "Owner Draws", "EQUITY", None, False, False),
    ("3900", "Retained Earnings", "EQUITY", None, False, False),
    ("4000", "Consulting Revenue", "INCOME", None, False, False),
    ("4900", "Other Income", "INCOME", None, False, False),
    ("6000", "Advertising", "EXPENSE", None, False, False),
    ("6050", "Bank and Card Fees", "EXPENSE", None, False, False),
    ("6100", "Software", "EXPENSE", None, False, False),
    ("6110", "Hosting", "EXPENSE", "6100", False, False),
    ("6120", "SaaS Subscriptions", "EXPENSE", "6100", False, False),
    ("6200", "Telephone and Internet", "EXPENSE", None, False, False),
    ("6300", "Travel", "EXPENSE", None, False, False),
    ("6350", "Meals", "EXPENSE", None, False, False),
    ("6400", "Office Supplies", "EXPENSE", None, False, False),
    ("6500", "Professional Fees", "EXPENSE", None, False, True),
    ("6600", "Insurance", "EXPENSE", None, False, False),
    ("6700", "Contract Labor", "EXPENSE", None, False, True),
    ("6800", "Taxes and Licenses", "EXPENSE", None, False, False),
    ("6900", "Miscellaneous", "EXPENSE", None, False, False),
]

# Each raises SQLSTATE 45000 with a message naming the rule. utils/journal.py checks the
# same rules first, so the owner sees a readable error; these catch what bypasses the
# app (phpMyAdmin, an ad-hoc SQL session). TRUNCATE does not fire DELETE triggers,
# which is what lets the test suite reset tables.
TRIGGERS = {
    "trg_journal_line_before_insert": """
        CREATE TRIGGER trg_journal_line_before_insert BEFORE INSERT ON journal_line
        FOR EACH ROW
        BEGIN
            IF NEW.amount = 0 THEN
                SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'journal_line: a line amount cannot be 0.00';
            END IF;
            IF EXISTS (
                SELECT 1 FROM journal_entry e JOIN settings s ON s.id = 1
                WHERE e.id = NEW.entry_id
                  AND s.lock_date IS NOT NULL
                  AND e.entry_date <= s.lock_date
            ) THEN
                SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'journal_line: the entry is dated on or before the lock date';
            END IF;
        END
    """,
    "trg_journal_line_before_update": """
        CREATE TRIGGER trg_journal_line_before_update BEFORE UPDATE ON journal_line
        FOR EACH ROW
        BEGIN
            IF NOT (NEW.entry_id <=> OLD.entry_id AND NEW.account_id <=> OLD.account_id
                    AND NEW.amount <=> OLD.amount AND NEW.line_no <=> OLD.line_no) THEN
                SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'journal_line: posted lines are immutable; only memo and cleared_recon_id may change';
            END IF;
        END
    """,
    "trg_journal_line_before_delete": """
        CREATE TRIGGER trg_journal_line_before_delete BEFORE DELETE ON journal_line
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'journal_line: posted lines are never deleted; post a reversal'
    """,
    # Not in DESIGN.md 3.2a's list of three, added for the same reason: editing an
    # entry's date in phpMyAdmin would move its lines across the lock date without
    # touching journal_line at all.
    "trg_journal_entry_before_update": """
        CREATE TRIGGER trg_journal_entry_before_update BEFORE UPDATE ON journal_entry
        FOR EACH ROW
        BEGIN
            IF NOT (NEW.entry_date <=> OLD.entry_date AND NEW.source <=> OLD.source
                    AND NEW.payee_id <=> OLD.payee_id
                    AND NEW.reverses_entry_id <=> OLD.reverses_entry_id
                    AND NEW.created_at <=> OLD.created_at) THEN
                SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'journal_entry: posted entries are immutable; only memo may change';
            END IF;
            IF OLD.reversed_by_entry_id IS NOT NULL
               AND NOT (NEW.reversed_by_entry_id <=> OLD.reversed_by_entry_id) THEN
                SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'journal_entry: a reversal link cannot be changed once set';
            END IF;
        END
    """,
    "trg_journal_entry_before_delete": """
        CREATE TRIGGER trg_journal_entry_before_delete BEFORE DELETE ON journal_entry
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'journal_entry: posted entries are never deleted; post a reversal'
    """,
}


def upgrade() -> None:
    op.create_table(
        "account",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("number", sa.String(10), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("type", sa.Enum("ASSET", "LIABILITY", "EQUITY", "INCOME", "EXPENSE"), nullable=False),
        sa.Column("parent_id", sa.Integer, sa.ForeignKey("account.id"), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_bank_account", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("tax_line", sa.String(60), nullable=True),
        sa.Column("is_1099_expense", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("description", sa.String(255), nullable=True),
        sa.UniqueConstraint("number", name="uq_account_number"),
        **TABLE_ARGS,
    )

    op.create_table(
        "payee",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("is_customer", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_vendor", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("address", sa.Text, nullable=True),
        sa.Column("default_account_id", sa.Integer, sa.ForeignKey("account.id"), nullable=True),
        sa.Column("is_1099_vendor", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("tax_id_ref", sa.String(60), nullable=True),
        sa.Column("payment_terms_days", sa.Integer, nullable=False, server_default="15"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("name", name="uq_payee_name"),
        **TABLE_ARGS,
    )

    op.create_table(
        "journal_entry",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("entry_date", sa.Date, nullable=False),
        sa.Column("memo", sa.String(255), nullable=True),
        sa.Column("source", sa.Enum("MANUAL", "BANK", "INVOICE", "PAYMENT", "OPENING", "REVERSAL", "IMPORT"),
                  nullable=False),
        sa.Column("payee_id", sa.Integer, sa.ForeignKey("payee.id"), nullable=True),
        sa.Column("reverses_entry_id", sa.BigInteger, sa.ForeignKey("journal_entry.id"), nullable=True),
        sa.Column("reversed_by_entry_id", sa.BigInteger, sa.ForeignKey("journal_entry.id"), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Index("ix_entry_date", "entry_date"),
        **TABLE_ARGS,
    )

    op.create_table(
        "journal_line",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("entry_id", sa.BigInteger, sa.ForeignKey("journal_entry.id"), nullable=False),
        sa.Column("line_no", sa.SmallInteger, nullable=False),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("account.id"), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("memo", sa.String(255), nullable=True),
        # Set when reconciled (phase 6); the reconciliation table arrives then.
        sa.Column("cleared_recon_id", sa.Integer, nullable=True),
        sa.UniqueConstraint("entry_id", "line_no", name="uq_line"),
        sa.Index("ix_line_account", "account_id", "entry_id"),
        **TABLE_ARGS,
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("object_type", sa.String(40), nullable=False),
        sa.Column("object_id", sa.BigInteger, nullable=True),
        sa.Column("detail", sa.JSON, nullable=True),
        **TABLE_ARGS,
    )

    op.add_column("settings", sa.Column("company_address", sa.Text, nullable=True))
    op.add_column("settings", sa.Column("fiscal_year_start_month", sa.SmallInteger,
                                        nullable=False, server_default="1"))
    op.add_column("settings", sa.Column("lock_date", sa.Date, nullable=True))
    # Nullable only until the seed below fills them; made NOT NULL straight after.
    op.add_column("settings", sa.Column("ar_account_id", sa.Integer, nullable=True))
    op.add_column("settings", sa.Column("retained_earnings_account_id", sa.Integer, nullable=True))

    account = sa.table(
        "account",
        sa.column("id", sa.Integer), sa.column("number", sa.String), sa.column("name", sa.String),
        sa.column("type", sa.String), sa.column("parent_id", sa.Integer),
        sa.column("is_bank_account", sa.Boolean), sa.column("is_1099_expense", sa.Boolean),
    )
    conn = op.get_bind()
    ids: dict[str, int] = {}
    for number, name, type_, parent, is_bank, is_1099 in SEED_CHART:
        result = conn.execute(account.insert().values(
            number=number, name=name, type=type_, parent_id=ids.get(parent) if parent else None,
            is_bank_account=is_bank, is_1099_expense=is_1099,
        ))
        # lastrowid, not inserted_primary_key: this lightweight table() declares no
        # primary key, so SQLAlchemy has none to report.
        ids[number] = result.lastrowid

    conn.execute(
        sa.text("UPDATE settings SET ar_account_id = :ar, retained_earnings_account_id = :re WHERE id = 1"),
        {"ar": ids["1200"], "re": ids["3900"]},
    )
    op.alter_column("settings", "ar_account_id", existing_type=sa.Integer, nullable=False)
    op.alter_column("settings", "retained_earnings_account_id", existing_type=sa.Integer, nullable=False)
    op.create_foreign_key("fk_settings_ar_account", "settings", "account", ["ar_account_id"], ["id"])
    op.create_foreign_key("fk_settings_re_account", "settings", "account",
                          ["retained_earnings_account_id"], ["id"])
    op.create_check_constraint("ck_settings_fy_month", "settings",
                               "fiscal_year_start_month BETWEEN 1 AND 12")

    for sql in TRIGGERS.values():
        op.execute(sql)


def downgrade() -> None:
    for name in TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_constraint("ck_settings_fy_month", "settings", type_="check")
    op.drop_constraint("fk_settings_re_account", "settings", type_="foreignkey")
    op.drop_constraint("fk_settings_ar_account", "settings", type_="foreignkey")
    for column in ("retained_earnings_account_id", "ar_account_id", "lock_date",
                   "fiscal_year_start_month", "company_address"):
        op.drop_column("settings", column)
    op.drop_table("audit_log")
    op.drop_table("journal_line")
    op.drop_table("journal_entry")
    op.drop_table("payee")
    op.drop_table("account")

""" EOF - 0002_core_ledger.py """
