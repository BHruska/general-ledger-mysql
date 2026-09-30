"""
General Ledger v0.4.1
File: routes/attachment_routes.py
Description: Receipts: list, upload (JSON with base64 content, like every other write --
             the CSRF defence in routes/auth_routes.py), view, remove.
"""

from flask import Blueprint, abort, request, send_file

from routes.api import body, envelope
from utils import attachments
from utils.errors import NotFound

attachment_bp = Blueprint("attachments", __name__)


@attachment_bp.route("/api/attachments", methods=["GET"])
@envelope
def list_attachments():
    return {"attachments": attachments.list_for(request.args.get("bank_txn_id", type=int),
                                                request.args.get("entry_id", type=int))}


@attachment_bp.route("/api/attachments", methods=["POST"])
@envelope
def upload():
    return {"attachment": attachments.upload(body())}


@attachment_bp.route("/api/attachments/<int:attachment_id>", methods=["DELETE"])
@envelope
def delete(attachment_id):
    attachments.delete(attachment_id)
    return {}


@attachment_bp.route("/attachments/<int:attachment_id>")
def view(attachment_id):
    """Inline in the browser. Safe to show inline only because the type was verified from
    the file's own bytes at upload: nothing but a PDF or an image is ever stored."""
    try:
        path, content_type, filename = attachments.open_file(attachment_id)
    except NotFound:
        abort(404)
    resp = send_file(path, mimetype=content_type, as_attachment=False, download_name=filename,
                     max_age=0)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "private, no-store"
    return resp

""" EOF - attachment_routes.py """
