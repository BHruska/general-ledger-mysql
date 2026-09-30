"""
General Ledger v0.2.0
File: routes/api.py
Description: The JSON envelope (docs/STYLING.md section 6.2), once. A LedgerError is the
             owner's mistake or the books' refusal and reads as a 400 (404 for NotFound);
             anything else is a bug, logged with its traceback, and a 500.
"""

import functools
import logging

from flask import jsonify, request

from utils.errors import LedgerError, NotFound

log = logging.getLogger(__name__)


def envelope(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            payload = fn(*args, **kwargs)
        except NotFound as e:
            return jsonify({"success": False, "error": str(e)}), 404
        except LedgerError as e:
            body = {"success": False, "error": str(e)}
            problems = getattr(e, "problems", None)
            if problems:
                body["problems"] = problems
            return jsonify(body), 400
        except Exception:
            log.exception("%s %s failed", request.method, request.path)
            return jsonify({"success": False, "error": "Internal error; see the server log."}), 500
        return jsonify({"success": True, **(payload or {})})
    return wrapper


def body() -> dict:
    """The JSON request body. The auth guard has already refused non-JSON writes."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise LedgerError("The request body must be a JSON object.")
    return data

""" EOF - api.py """
