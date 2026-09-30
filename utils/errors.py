"""
General Ledger v0.2.0
File: utils/errors.py
Description: Errors the owner is meant to read. Routes turn LedgerError into a 400
             envelope (NotFound into 404); anything else is a 500 and a log line.
"""


class LedgerError(Exception):
    """A request the books refuse, with a reason fit to show on screen."""


class NotFound(LedgerError):
    """The object named in the request does not exist."""

""" EOF - errors.py """
