"""
General Ledger v0.4.1
File: tests/test_attachments.py
Description: Receipts: upload to a bank line or entry, carried to the entry on posting,
             served back inline only as a verified PDF or image, removed with an audit row.
"""

import base64
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

import config
import db
from models import AuditLog
from utils import attachments, bank_accounts, bank_queue, journal
from utils.errors import LedgerError
from utils.feeds import file_import
from utils.journal import LineInput

CARD_CSV = (Path(__file__).resolve().parent / "fixtures" / "chase_card.csv").read_text()
PDF = b"%PDF-1.4\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


@pytest.fixture
def hosting_line(chart):
    ba = bank_accounts.create_file_account({"gl_account_id": chart["2010"], "name": "Card",
                                            "feed_start_date": "2026-07-01"})["id"]
    file_import.import_file(ba, CARD_CSV, None)
    return next(l for l in bank_queue.list_lines("review")["lines"] if l["description"] == "EXAMPLE HOSTING")


def test_receipt_on_a_bank_line_follows_it_into_the_entry(chart, hosting_line):
    a = attachments.upload({"bank_txn_id": hosting_line["id"], "filename": "C:\\Users\\me\\receipt.pdf",
                            "content_base64": b64(PDF)})
    assert (a["filename"], a["content_type"], a["entry_id"]) == ("receipt.pdf", "application/pdf", None)
    assert (Path(config.DATA_DIR) / "attachments").exists()
    line = next(l for l in bank_queue.list_lines("review")["lines"] if l["id"] == hosting_line["id"])
    assert line["attachments"] == 1

    entry_id = bank_queue.post_line(hosting_line["id"], {"account_id": chart["6110"]})["entry_id"]
    assert attachments.list_for(entry_id=entry_id)[0]["id"] == a["id"]
    entries = journal.list_entries(date(2026, 1, 1), date(2026, 12, 31))
    assert next(e for e in entries if e["id"] == entry_id)["attachments"] == 1


def test_receipt_added_after_posting_is_on_the_entry_too(chart, hosting_line):
    entry_id = bank_queue.post_line(hosting_line["id"], {"account_id": chart["6110"]})["entry_id"]
    a = attachments.upload({"bank_txn_id": hosting_line["id"], "filename": "late.png", "content_base64": b64(PNG)})
    assert a["entry_id"] == entry_id and a["content_type"] == "image/png"


def test_manual_entry_receipt(chart):
    with db.SessionLocal.begin() as session:
        entry_id = journal.post_entry(session, entry_date=date(2026, 3, 1), lines=[
            LineInput(chart["6300"], Decimal("5")), LineInput(chart["1010"], Decimal("-5"))]).id
    attachments.upload({"entry_id": entry_id, "filename": "taxi.jpg", "content_base64": b64(b"\xff\xd8\xff\xe0" + b"0" * 20)})
    assert len(attachments.list_for(entry_id=entry_id)) == 1


@pytest.mark.parametrize("payload, words", [
    ({"filename": "evil.pdf", "content_base64": b64(b"<html><script>alert(1)</script>")}, "Only PDF and image"),
    ({"filename": "x.pdf", "content_base64": "not base64!!"}, "did not arrive intact"),
    ({"filename": "x.pdf", "content_base64": ""}, "Choose a file"),
    ({"filename": "", "content_base64": b64(PDF)}, "no name"),
])
def test_refusals(chart, hosting_line, payload, words):
    with pytest.raises(LedgerError, match=words):
        attachments.upload({"bank_txn_id": hosting_line["id"], **payload})


def test_needs_exactly_one_target(chart, hosting_line):
    with pytest.raises(LedgerError, match="either"):
        attachments.upload({"filename": "x.pdf", "content_base64": b64(PDF)})
    with pytest.raises(LedgerError, match="either"):
        attachments.upload({"bank_txn_id": hosting_line["id"], "entry_id": 1, "filename": "x.pdf",
                            "content_base64": b64(PDF)})


def test_too_large(chart, hosting_line, monkeypatch):
    monkeypatch.setattr(attachments, "MAX_BYTES", 10)
    with pytest.raises(LedgerError, match="larger than 10 MB"):
        attachments.upload({"bank_txn_id": hosting_line["id"], "filename": "x.pdf", "content_base64": b64(PDF)})


def test_same_file_twice_is_stored_once_and_kept_until_last_removed(chart, hosting_line):
    first = attachments.upload({"bank_txn_id": hosting_line["id"], "filename": "a.pdf", "content_base64": b64(PDF)})
    second = attachments.upload({"bank_txn_id": hosting_line["id"], "filename": "b.pdf", "content_base64": b64(PDF)})
    path, _, _ = attachments.open_file(first["id"])
    assert attachments.open_file(second["id"])[0] == path
    attachments.delete(first["id"])
    assert path.exists()
    attachments.delete(second["id"])
    assert not path.exists()
    with db.SessionLocal() as session:
        assert [r.action for r in session.scalars(select(AuditLog).where(AuditLog.object_type == "attachment")
                                                  .order_by(AuditLog.id))] == \
            ["attachment.add", "attachment.add", "attachment.remove", "attachment.remove"]


def test_api_upload_view_delete(signed_in, chart, hosting_line):
    resp = signed_in.post("/api/attachments", json={"bank_txn_id": hosting_line["id"], "filename": "r.pdf",
                                                    "content_base64": b64(PDF)})
    assert resp.status_code == 200, resp.get_json()
    a = resp.get_json()["attachment"]
    view = signed_in.get(a["url"])
    assert view.status_code == 200 and view.data == PDF
    assert view.mimetype == "application/pdf" and view.headers["X-Content-Type-Options"] == "nosniff"
    view.close()  # release the file handle, as a finished browser download does
    listed = signed_in.get(f"/api/attachments?bank_txn_id={hosting_line['id']}").get_json()["attachments"]
    assert [x["id"] for x in listed] == [a["id"]]
    assert signed_in.delete(f"/api/attachments/{a['id']}", json={}).status_code == 200
    assert signed_in.get(a["url"]).status_code == 404


def test_viewing_needs_login(client):
    assert client.get("/attachments/1").status_code == 302

""" EOF - test_attachments.py """
