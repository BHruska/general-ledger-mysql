"""
General Ledger v0.2.0
File: utils/audit.py
Description: audit_log rows: every change that is not itself a posting (a memo edit,
             a lock-date move), so the books stay explainable from the rows alone.
"""

from datetime import datetime, timezone

from models import AuditLog


def utcnow() -> datetime:
    """Naive UTC for DATETIME(6) columns; the connection's time_zone is +00:00."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def record(session, action: str, object_type: str, object_id: int | None, detail: dict | None = None):
    session.add(AuditLog(at=utcnow(), action=action, object_type=object_type,
                         object_id=object_id, detail=detail))

""" EOF - audit.py """
