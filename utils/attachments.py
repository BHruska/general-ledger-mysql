"""
General Ledger v0.4.1
File: utils/attachments.py
Description: Receipts on bank lines and journal entries (docs/DESIGN.md sections 3.2, 6.2
             and 11). Files live under /data/attachments/yyyy/mm/<sha256>.<ext>, which is
             backed up nightly; the table says what each is attached to.

Adding or removing an attachment changes no amount, date or account, so it is allowed on
a posted entry (DESIGN.md 3.2) and recorded in audit_log.
"""

import base64
import binascii
import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select, update

import config
from db import SessionLocal
from models import Attachment, BankTxn, JournalEntry
from utils import audit
from utils.errors import LedgerError, NotFound

log = logging.getLogger(__name__)

MAX_BYTES = 10 * 1024 * 1024
FILENAME_MAX = 255

# Identified by the file's first bytes, never by its name or a browser's claim: only a
# real PDF or image is ever stored, and so only those are ever served back inline.
SIGNATURES = [
    (b"%PDF-", "application/pdf", "pdf"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"GIF87a", "image/gif", "gif"),
    (b"GIF89a", "image/gif", "gif"),
]


def _sniff(data: bytes) -> tuple[str, str]:
    for magic, content_type, ext in SIGNATURES:
        if data.startswith(magic):
            return content_type, ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"mif1", b"msf1"):
        return "image/heic", "heic"  # iPhone photos
    raise LedgerError("Only PDF and image files (JPEG, PNG, GIF, WebP, HEIC) can be attached.")


def _data_dir() -> Path:
    return Path(config.DATA_DIR)


def serialize(a: Attachment) -> dict:
    return {
        "id": a.id,
        "filename": a.filename,
        "content_type": a.content_type,
        "size_bytes": a.size_bytes,
        "uploaded_at": a.uploaded_at.isoformat(),
        "entry_id": a.entry_id,
        "bank_txn_id": a.bank_txn_id,
        "url": f"/attachments/{a.id}",
    }


def _store(data: bytes, sha: str, ext: str, now: datetime) -> str:
    relative = Path("attachments") / f"{now:%Y}" / f"{now:%m}" / f"{sha}.{ext}"
    target = _data_dir() / relative
    if not target.exists():  # identical content is stored once
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.tmp")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(target)  # atomic: a crash never leaves half a receipt
    return relative.as_posix()


def upload(data: dict) -> dict:
    bank_txn_id, entry_id = data.get("bank_txn_id"), data.get("entry_id")
    if bool(bank_txn_id) == bool(entry_id):
        raise LedgerError("Attach to either a bank line or a journal entry.")
    filename = (data.get("filename") or "").strip().replace("\\", "/").split("/")[-1][:FILENAME_MAX]
    if not filename:
        raise LedgerError("The file has no name.")
    content = data.get("content_base64")
    if not isinstance(content, str) or not content:
        raise LedgerError("Choose a file.")
    if len(content) > MAX_BYTES * 4 // 3 + 16:
        raise LedgerError("The file is larger than 10 MB.")
    try:
        raw = base64.b64decode(content, validate=True)
    except (binascii.Error, ValueError):
        raise LedgerError("The file did not arrive intact; try again.") from None
    if not raw:
        raise LedgerError("The file is empty.")
    if len(raw) > MAX_BYTES:
        raise LedgerError("The file is larger than 10 MB.")
    content_type, ext = _sniff(raw)
    sha = hashlib.sha256(raw).hexdigest()

    with SessionLocal.begin() as session:
        if bank_txn_id:
            txn = session.get(BankTxn, int(bank_txn_id))
            if txn is None:
                raise NotFound(f"Bank line {bank_txn_id} does not exist.")
            # Already posted: the receipt belongs to the entry too, so it shows from the journal.
            entry_id = txn.entry_id
        elif session.get(JournalEntry, int(entry_id)) is None:
            raise NotFound(f"Entry {entry_id} does not exist.")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        a = Attachment(entry_id=int(entry_id) if entry_id else None,
                       bank_txn_id=int(bank_txn_id) if bank_txn_id else None,
                       filename=filename, stored_path=_store(raw, sha, ext, now), sha256=sha,
                       content_type=content_type, size_bytes=len(raw), uploaded_at=now)
        session.add(a)
        session.flush()
        audit.record(session, "attachment.add", "attachment", a.id,
                     {"filename": filename, "sha256": sha, "entry_id": a.entry_id, "bank_txn_id": a.bank_txn_id})
        return serialize(a)


def list_for(bank_txn_id: int | None = None, entry_id: int | None = None) -> list[dict]:
    if not bank_txn_id and not entry_id:
        raise LedgerError("Name a bank line or an entry.")
    with SessionLocal() as session:
        stmt = select(Attachment).order_by(Attachment.uploaded_at)
        if bank_txn_id:
            stmt = stmt.where(Attachment.bank_txn_id == bank_txn_id)
        else:
            stmt = stmt.where(Attachment.entry_id == entry_id)
        return [serialize(a) for a in session.scalars(stmt)]


def counts(session, *, bank_txn_ids=(), entry_ids=()) -> dict[int, int]:
    """Attachment counts for the rows on a page, in one query."""
    column = Attachment.bank_txn_id if bank_txn_ids else Attachment.entry_id
    ids = set(bank_txn_ids or entry_ids)
    if not ids:
        return {}
    return dict(session.execute(select(column, func.count()).where(column.in_(ids)).group_by(column)).all())


def carry_to_entry(session, bank_txn_ids, entry_id: int) -> None:
    """Posting a bank line attaches its receipts to the new entry (DESIGN.md 6.2)."""
    session.execute(update(Attachment).where(Attachment.bank_txn_id.in_(set(bank_txn_ids)))
                    .values(entry_id=entry_id))


def open_file(attachment_id: int) -> tuple[Path, str, str]:
    with SessionLocal() as session:
        a = session.get(Attachment, attachment_id)
        if a is None:
            raise NotFound(f"Attachment {attachment_id} does not exist.")
        root = _data_dir().resolve()
        path = (root / a.stored_path).resolve()
        if root not in path.parents:
            raise NotFound("Attachment path is outside the data directory.")
        if not path.is_file():
            raise NotFound(f"The file for attachment {attachment_id} is missing from {root}.")
        return path, a.content_type, a.filename


def delete(attachment_id: int) -> None:
    with SessionLocal.begin() as session:
        a = session.get(Attachment, attachment_id)
        if a is None:
            raise NotFound(f"Attachment {attachment_id} does not exist.")
        stored = a.stored_path
        audit.record(session, "attachment.remove", "attachment", a.id,
                     {"filename": a.filename, "sha256": a.sha256, "entry_id": a.entry_id,
                      "bank_txn_id": a.bank_txn_id})
        session.delete(a)
        session.flush()
        still_used = session.scalar(select(func.count()).select_from(Attachment)
                                    .where(Attachment.stored_path == stored))
    if not still_used:
        # The row is already gone and the removal audited. A file that cannot be deleted
        # right now (held open by a download, say) is an orphan under /data, harmless,
        # and must not turn a completed removal into an error.
        try:
            (_data_dir() / stored).unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warning("attachment %s removed, but its file could not be deleted yet: %s", attachment_id, e)

""" EOF - attachments.py """
