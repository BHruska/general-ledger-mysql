"""
General Ledger v0.1.0
File: utils/credentials.py
Description: Resolves a credential by NAME, strongest source first. Implements
             docs/CREDENTIALS.md sections 2 and 3.

Copied from trade-portfolio/utils/credentials.py (v0.6.0), as CREDENTIALS.md section 6
says, with that app's wallet and exchange helpers removed and the names changed. The
tier order and the warnings are unchanged.

The database and the repo hold a `credential_ref` -- a name. The value is resolved
here, at use, and never stored, logged or returned anywhere it could be printed by
accident.

Tiers, in the order they are tried:

  1. OS keyring      natively-run tools. Unreachable from a container.
  2. encrypted file  <ref>.enc, Argon2id + AES-256-GCM. The container's real option.
  3. plain file      the NEW-APP-INTEGRATION.md baseline, /etc/general-ledger/<ref>.
  4. environment     GL_CRED_<REF>.

Tiers 3 and 4 log a warning every time they are used, because a development shortcut
that stays silent is how plaintext reaches production.
"""

import hashlib
import logging
import os
from dataclasses import dataclass

import config
from utils import keystore

log = logging.getLogger(__name__)

APP_SERVICE = "GENERAL_LEDGER:{ref}"
APP_USERNAME = "secret"

ENV_PREFIX = "GL_CRED_"

ENCRYPTED_SUFFIX = keystore.SUFFIX

# The passphrase that unlocks every encrypted credential for this app. It must NOT
# live beside the ciphertext, or the encryption protects nothing. On the server:
# passphrase in env/general-ledger.env (the infra repo tree), ciphertext under
# /opt/data/secrets (the data tree). See docs/CREDENTIALS.md section 2.
PASSPHRASE_ENV = "GL_KEYSTORE_PASSPHRASE"


class CredentialError(Exception):
    """A credential was asked for and could not be produced."""


@dataclass(frozen=True)
class Resolution:
    """Where a credential came from -- never what it is."""

    ref: str
    source: str
    weak: bool
    fingerprint: str


def _fingerprint(value: str) -> str:
    """A stable, non-reversible handle for a secret. A hash, never a prefix."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _from_keyring(ref: str) -> str | None:
    try:
        import keyring
    except ImportError:
        return None
    try:
        value = keyring.get_password(APP_SERVICE.format(ref=ref), APP_USERNAME)
    except Exception:
        # No backend at all: normal inside a container, where Secret Service does not
        # exist. Not an error -- fall through to the next tier.
        return None
    return value.strip() if value else None


def _from_plain_file(ref: str) -> tuple[str | None, str | None]:
    base = config.SECRETS_DIR / ref
    for candidate in (base, base.with_suffix(".txt"), base.with_suffix(".key")):
        try:
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8").strip(), str(candidate)
        except OSError as e:
            # A mount present but unreadable is almost always a UID mismatch on the
            # secrets directory, which otherwise reads as a bad credential.
            log.warning("credential %s: cannot read %s (%s)", ref, candidate, e)
    return None, None


def _from_env(ref: str) -> str | None:
    value = os.getenv(ENV_PREFIX + ref.upper().replace("-", "_"))
    return value.strip() if value else None


def resolve(ref: str) -> tuple[str, Resolution]:
    """Return the value and where it came from. Raises if nothing has it."""
    if not ref:
        raise CredentialError("No credential_ref was given.")

    value = _from_keyring(ref)
    if value:
        return value, Resolution(ref, "keyring", False, _fingerprint(value))

    encrypted = config.SECRETS_DIR / (ref + ENCRYPTED_SUFFIX)
    if encrypted.is_file():
        passphrase = os.getenv(PASSPHRASE_ENV, "")
        if not passphrase:
            raise CredentialError(
                f"{encrypted} is encrypted but {PASSPHRASE_ENV} is not set. "
                "Without it this credential cannot be opened."
            )
        try:
            value = keystore.read(encrypted, passphrase)
        except keystore.KeystoreError as e:
            raise CredentialError(str(e)) from e
        finally:
            del passphrase
        return value, Resolution(ref, "encrypted_file", False, _fingerprint(value))

    value, path = _from_plain_file(ref)
    if value:
        log.warning(
            "credential %s resolved from a PLAIN FILE (%s). Acceptable in development; "
            "see docs/CREDENTIALS.md section 2.",
            ref, path,
        )
        return value, Resolution(ref, "plain_file", True, _fingerprint(value))

    value = _from_env(ref)
    if value:
        log.warning(
            "credential %s resolved from the ENVIRONMENT (%s%s). Readable by anything "
            "in this process; see docs/CREDENTIALS.md section 2.",
            ref, ENV_PREFIX, ref.upper(),
        )
        return value, Resolution(ref, "environment", True, _fingerprint(value))

    raise CredentialError(
        f"No credential named '{ref}' was found. Looked in the OS keyring "
        f"({APP_SERVICE.format(ref=ref)}), {config.SECRETS_DIR}/{ref}{ENCRYPTED_SUFFIX}, "
        f"{config.SECRETS_DIR}/{ref}, and {ENV_PREFIX}{ref.upper()}."
    )


def get(ref: str) -> str:
    """The value alone. Never log the return of this function."""
    value, _ = resolve(ref)
    return value


def describe(ref: str) -> dict:
    """Where a credential lives and how strongly, without revealing it."""
    try:
        _, resolution = resolve(ref)
    except CredentialError as e:
        return {"ref": ref, "source": None, "weak": None, "fingerprint": None,
                "available": False, "error": str(e)}
    return {
        "ref": resolution.ref,
        "source": resolution.source,
        "weak": resolution.weak,
        "fingerprint": resolution.fingerprint,
        "available": True,
        "error": None,
    }


def write_encrypted(ref: str, value: str, passphrase: str, label: str = "",
                    overwrite: bool = False) -> Resolution:
    """Encrypt a credential into the secrets directory."""
    value = (value or "").strip()
    if not value:
        raise CredentialError("Refusing to store an empty credential.")
    path = config.SECRETS_DIR / (ref + ENCRYPTED_SUFFIX)
    try:
        keystore.write(path, value, passphrase, label=label, overwrite=overwrite)
    except keystore.KeystoreError as e:
        raise CredentialError(str(e)) from e
    return Resolution(ref, "encrypted_file", False, _fingerprint(value))


def put_keyring(ref: str, value: str) -> Resolution:
    """Store a credential in the OS keyring. Developer setup only."""
    try:
        import keyring
    except ImportError as e:
        raise CredentialError(
            "the 'keyring' package is not installed; run: pip install keyring"
        ) from e

    value = (value or "").strip()
    if not value:
        raise CredentialError("Refusing to store an empty credential.")
    try:
        keyring.set_password(APP_SERVICE.format(ref=ref), APP_USERNAME, value)
    except Exception as e:
        raise CredentialError(f"Could not write to the OS keyring: {e}") from e
    return Resolution(ref, "keyring", False, _fingerprint(value))


def delete_keyring(ref: str) -> None:
    try:
        import keyring
    except ImportError as e:
        raise CredentialError("the 'keyring' package is not installed") from e
    try:
        keyring.delete_password(APP_SERVICE.format(ref=ref), APP_USERNAME)
    except Exception:
        pass

""" EOF - credentials.py """
