"""
General Ledger v0.2.0
File: utils/money.py
Description: Decimal in, Decimal out. Amounts cross the API as strings ("1234.56"),
             never as JSON numbers, so no float ever touches a figure.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from utils.errors import LedgerError

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def parse_amount(value, what: str = "amount") -> Decimal:
    """A string or Decimal with at most two decimal places. Refuses floats outright.

    More than two places is refused rather than rounded: a figure the owner typed as
    10.005 is a typo, and silently making it 10.01 would put a number in the books
    nobody entered.
    """
    if isinstance(value, bool) or isinstance(value, float):
        raise LedgerError(f"{what} must be sent as a string, not a JSON number.")
    if isinstance(value, int):
        value = str(value)
    if isinstance(value, str):
        value = value.strip().replace(",", "").replace("$", "")
        if not value:
            raise LedgerError(f"{what} is empty.")
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise LedgerError(f"{what} is not a number: {value!r}") from None
    if not amount.is_finite():
        raise LedgerError(f"{what} is not a number: {value!r}")
    if amount != amount.quantize(CENT):
        raise LedgerError(f"{what} has more than two decimal places: {value}")
    if abs(amount) >= Decimal("1000000000000"):
        raise LedgerError(f"{what} is too large: {value}")
    return amount.quantize(CENT)


def parse_optional_amount(value, what: str = "amount") -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return parse_amount(value, what)


def parse_date(value, what: str = "date") -> date:
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        raise LedgerError(f"{what} is required (YYYY-MM-DD).")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise LedgerError(f"{what} is not a date (YYYY-MM-DD): {value!r}") from None


def parse_optional_date(value, what: str = "date") -> date | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return parse_date(value, what)


def to_str(amount: Decimal | None) -> str | None:
    """The API's representation. None stays None: an absent figure is an em dash.

    Decimal keeps the sign of zero, so a zero balance flipped into a credit account's
    normal direction is Decimal('-0.00'); it must never reach a page as "-$0.00".
    """
    if amount is None:
        return None
    return str(ZERO if amount == 0 else amount.quantize(CENT))

""" EOF - money.py """
