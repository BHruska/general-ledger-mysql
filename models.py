"""
General Ledger v0.1.0
File: models.py
Description: ORM models. Phase 0 holds only the login columns of `settings`; the
             rest of docs/DESIGN.md section 4 arrives with the phases that use it.
"""

from sqlalchemy import SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class Settings(Base):
    """The one-row settings table (id is always 1).

    DESIGN.md section 4 declares owner_password_hash NOT NULL. It is nullable here
    because the row exists before anyone has chosen a password: `manage.py
    set-password` fills it, and login refuses while it is NULL. Phase 1 adds the
    account columns (ar_account_id, retained_earnings_account_id, lock_date, ...)
    once the chart of accounts they reference exists.
    """

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    company_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    owner_password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # A credential_ref, never the TOTP secret itself (docs/CREDENTIALS.md section 4).
    totp_secret_ref: Mapped[str | None] = mapped_column(String(60), nullable=True)

""" EOF - models.py """
