"""
General Ledger v0.1.0
File: utils/keystore.py
Description: Argon2id + AES-256-GCM credential files. Tier 2 of docs/CREDENTIALS.md.

Copied unchanged from trade-portfolio/utils/keystore.py (v0.6.0), which was ported
from trade-solana/trade_solana/keystore.py, the canonical implementation of this format. That one wraps a Solana keypair; this one wraps an
arbitrary text credential (an xpub, an API key), so the payload is UTF-8 rather than
32 raw bytes and the non-secret `label` replaces `pubkey`. The header, KDF parameters
and AAD binding are deliberately identical, so a file written by either is readable by
the same code.

Why this tier exists: a container cannot reach an OS keyring, so on a server the only
alternative is plaintext. See docs/CREDENTIALS.md section 2.

File format (v1), JSON:

    {
      "version": 1,
      "kdf": "argon2id",
      "kdf_params": {"memory_cost_kib": 262144, "iterations": 3,
                     "lanes": 4, "salt": "<b64>"},
      "cipher": "aes-256-gcm",
      "nonce": "<b64>",
      "ciphertext": "<b64>",
      "label": "<non-secret identifier>",
      "created_at": "<iso8601>"
    }

The header is bound into the ciphertext as AES-GCM associated data, so editing any of
it -- swapping in weaker KDF parameters, changing the recorded label -- makes
decryption fail rather than silently succeed.
"""

import base64
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

KEYSTORE_VERSION = 1
SUFFIX = ".enc"

# RFC 9106's second recommended profile, scaled up: about 0.3 s and 256 MiB on a 2026
# machine. Cheap once per resolution, expensive to brute force. Recorded per file, so
# raising these later does not make existing files unreadable.
KDF_PARAMS = {"memory_cost_kib": 262144, "iterations": 3, "lanes": 4}

_B64 = base64.b64encode
_UNB64 = base64.b64decode


class KeystoreError(Exception):
    """A keystore could not be read, written or decrypted."""


def _derive_key(passphrase: str, salt: bytes, params: dict) -> bytes:
    try:
        from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
    except ImportError as exc:
        raise KeystoreError(
            "Argon2id needs cryptography >= 44; this build has an older one. "
            "Update requirements.txt and rebuild."
        ) from exc

    try:
        return Argon2id(
            salt=salt,
            length=32,
            iterations=int(params["iterations"]),
            lanes=int(params["lanes"]),
            memory_cost=int(params["memory_cost_kib"]),
        ).derive(passphrase.encode("utf-8"))
    except (ValueError, TypeError, KeyError) as exc:
        # A tampered header can carry parameters Argon2id rejects outright -- setting
        # memory_cost below 8*lanes, for instance. That must read as a bad keystore,
        # not escape as a library traceback from somewhere deep in a sync.
        raise KeystoreError(
            "keystore header is invalid or has been modified: bad KDF parameters"
        ) from exc


def _header_aad(doc: dict) -> bytes:
    """Canonical bytes of everything that must not be tampered with."""
    return json.dumps(
        {
            "version": doc["version"],
            "kdf": doc["kdf"],
            "kdf_params": doc["kdf_params"],
            "cipher": doc["cipher"],
            "label": doc["label"],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _read_doc(path: Path) -> dict:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise KeystoreError(f"cannot read {path}: {exc}") from exc
    except ValueError as exc:
        raise KeystoreError(f"{path} is not valid JSON") from exc

    if doc.get("version") != KEYSTORE_VERSION:
        raise KeystoreError(
            f"keystore version {doc.get('version')!r} is not supported "
            f"(this build understands version {KEYSTORE_VERSION})"
        )
    if doc.get("kdf") != "argon2id" or doc.get("cipher") != "aes-256-gcm":
        raise KeystoreError(
            f"unsupported algorithms: kdf={doc.get('kdf')!r} cipher={doc.get('cipher')!r}"
        )
    return doc


def label_of(path: Path) -> str | None:
    """The non-secret identifier, readable without the passphrase."""
    try:
        return _read_doc(path).get("label")
    except KeystoreError:
        return None


def read(path: Path, passphrase: str) -> str:
    """Decrypt and return the credential."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    doc = _read_doc(path)
    if not passphrase:
        raise KeystoreError(f"{path} needs a passphrase and none was supplied")

    key = _derive_key(passphrase, _UNB64(doc["kdf_params"]["salt"]), doc["kdf_params"])
    try:
        plaintext = AESGCM(key).decrypt(
            _UNB64(doc["nonce"]), _UNB64(doc["ciphertext"]), _header_aad(doc)
        )
    except InvalidTag as exc:
        # One message for both causes on purpose: distinguishing "wrong passphrase"
        # from "file modified" would tell an attacker which half they got right.
        raise KeystoreError(
            f"could not decrypt {path}: wrong passphrase, or the file has been modified."
        ) from exc
    finally:
        del key

    return plaintext.decode("utf-8")


def write(path: Path, value: str, passphrase: str, label: str = "", overwrite: bool = False) -> str:
    """Encrypt `value` to `path`. Returns the path written."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    path = Path(path)
    if path.exists() and not overwrite:
        raise KeystoreError(f"{path} already exists; refusing to overwrite it.")
    if len(passphrase or "") < 8:
        raise KeystoreError("passphrase must be at least 8 characters")

    salt, nonce = os.urandom(16), os.urandom(12)
    params = dict(KDF_PARAMS, salt=_B64(salt).decode())

    doc = {
        "version": KEYSTORE_VERSION,
        "kdf": "argon2id",
        "kdf_params": params,
        "cipher": "aes-256-gcm",
        "label": label or "",
    }
    key = _derive_key(passphrase, salt, params)
    try:
        ciphertext = AESGCM(key).encrypt(nonce, value.encode("utf-8"), _header_aad(doc))
    finally:
        del key

    doc["nonce"] = _B64(nonce).decode()
    doc["ciphertext"] = _B64(ciphertext).decode()
    doc["created_at"] = datetime.now(timezone.utc).isoformat()

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    # Created owner-only from the start rather than chmod-ed afterwards: between
    # creation and chmod the file would briefly be world-readable.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    try:
        os.write(fd, json.dumps(doc, indent=2).encode("utf-8"))
    finally:
        os.close(fd)
    # Atomic: a crash mid-write cannot leave a truncated keystore in place.
    tmp.replace(path)
    return str(path)


def change_passphrase(path: Path, old: str, new: str) -> None:
    value = read(path, old)
    try:
        label = label_of(path) or ""
        write(path, value, new, label=label, overwrite=True)
    finally:
        del value

""" EOF - keystore.py """
