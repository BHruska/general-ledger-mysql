"""
General Ledger v0.1.0
File: utils/auth.py
Description: The owner login (docs/DESIGN.md section 11): Argon2id password hash in
             settings.owner_password_hash, checked here. Routes stay thin.
"""

import hashlib

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

import config
from db import SessionLocal
from models import Settings

# argon2-cffi's defaults are RFC 9106's low-memory profile. One login at a time for
# one owner, so the cost is paid rarely and a stolen hash is expensive to attack.
_hasher = PasswordHasher()


class AuthError(Exception):
    """A login could not be completed, with a reason fit to show the owner."""


def hash_password(password: str) -> str:
    if len(password) < config.MIN_PASSWORD_LENGTH:
        raise AuthError(f"Use at least {config.MIN_PASSWORD_LENGTH} characters.")
    return _hasher.hash(password)


def _settings(session) -> Settings:
    row = session.get(Settings, 1)
    if row is None:
        # Migration 0001 inserts it; its absence means the schema was built by hand.
        raise AuthError("The settings row is missing. Run `alembic upgrade head`.")
    return row


def password_epoch(password_hash: str | None) -> str | None:
    """A short, non-reversible tag of the CURRENT hash, stored in the session.

    Changing the password changes the hash, which changes this tag, which ends every
    existing session on its next request. Without it a stolen cookie would outlive a
    password change by up to the 12-hour idle limit.
    """
    if not password_hash:
        return None
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def current_epoch() -> str | None:
    with SessionLocal() as session:
        return password_epoch(_settings(session).owner_password_hash)


def verify_login(password: str) -> str:
    """Check the owner password. Returns the epoch tag to store in the session."""
    with SessionLocal() as session:
        row = _settings(session)
        stored = row.owner_password_hash
        if not stored:
            raise AuthError(
                "No owner password is set. Run `python manage.py set-password` in the container."
            )
        try:
            _hasher.verify(stored, password)
        except VerifyMismatchError:
            raise AuthError("Wrong password.") from None
        except (VerificationError, InvalidHashError) as e:
            raise AuthError("The stored password hash is unreadable; set it again.") from e

        # Parameters raised since this hash was made: re-hash now, while the plaintext
        # is in hand, so the stored hash keeps up without a reset.
        if _hasher.check_needs_rehash(stored):
            row.owner_password_hash = _hasher.hash(password)
            session.commit()
            stored = row.owner_password_hash
        return password_epoch(stored)


def set_password(password: str) -> None:
    new_hash = hash_password(password)
    with SessionLocal() as session:
        _settings(session).owner_password_hash = new_hash
        session.commit()

""" EOF - auth.py """
