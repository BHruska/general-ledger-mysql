#!/usr/bin/env python3
"""
General Ledger v0.1.0
File: credential.py
Description: Store and inspect credentials without them touching shell history or a
             terminal transcript. See docs/CREDENTIALS.md section 6.

    python credential.py set session_secret --encrypted   # hidden prompt -> keystore
    python credential.py set plaid_sandbox --file         # hidden prompt -> plaintext file
    python credential.py encrypt plaid_sandbox            # convert an existing plain file
    python credential.py passwd                           # re-key every keystore
    python credential.py status session_secret

Trimmed from trade-portfolio's credential.py: the wallet and exchange commands are gone.
A `list` of the refs the database expects arrives with bank_connection (phase 4).

`set` reads the value from a hidden prompt on purpose. Passing a secret as a command
argument puts it in shell history, in the process list, and in any terminal recording.

Use --encrypted or --file for anything THIS app must read. The app runs in a container
and a container cannot reach the OS keyring -- not even on your own workstation.
"""

import argparse
import sys
from getpass import getpass

from utils import credentials, keystore


def _write_secret_file(ref: str, value: str) -> str:
    """Write to the secrets directory, owner-readable only, atomically."""
    import os
    import stat

    import config

    directory = config.SECRETS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    try:
        directory.chmod(stat.S_IRWXU)  # 700; a no-op on Windows ACLs
    except OSError:
        pass

    target = directory / ref
    tmp = directory / f".{ref}.tmp"
    # Created with restrictive permissions from the start rather than chmod-ed after:
    # between creation and chmod the secret would briefly be world-readable.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    try:
        os.write(fd, (value + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    tmp.replace(target)
    return str(target)


def _passphrase(confirm: bool = False) -> str:
    """The keystore passphrase, from the environment or a hidden prompt."""
    import os

    value = os.getenv(credentials.PASSPHRASE_ENV)
    if value:
        print(f"Using the passphrase from {credentials.PASSPHRASE_ENV}.")
        return value
    value = getpass("Keystore passphrase: ")
    if confirm and getpass("Confirm passphrase: ") != value:
        raise ValueError("passphrases did not match")
    if len(value) < 8:
        raise ValueError("passphrase must be at least 8 characters")
    return value


def cmd_set(args) -> int:
    destination = ("encrypted file" if args.encrypted
                   else "secrets file" if args.file else "OS keyring")
    print(f"Storing '{args.ref}' in the {destination}.")
    if not args.file and not args.encrypted:
        print("NOTE: the containerised app cannot read the OS keyring. Use --encrypted")
        print("      (or --file) for anything this app must resolve itself.")
    print("Input is hidden and is not echoed, logged or written anywhere else.")
    try:
        value = getpass("Value: ")
        if getpass("Confirm: ") != value:
            print("Values did not match; nothing stored.", file=sys.stderr)
            return 1
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.", file=sys.stderr)
        return 1

    value = value.strip()
    if not value:
        print("Empty value; nothing stored.", file=sys.stderr)
        return 1

    try:
        if args.encrypted:
            passphrase = _passphrase(confirm=True)
            resolution = credentials.write_encrypted(
                args.ref, value, passphrase, label=args.label or "", overwrite=args.force
            )
            del passphrase
            print(f"\nEncrypted. fingerprint={resolution.fingerprint}  source={resolution.source}")
        elif args.file:
            path = _write_secret_file(args.ref, value)
            print(f"\nStored at {path} (mode 600). fingerprint={credentials._fingerprint(value)}")
            print("That path is gitignored. It is PLAINTEXT: fine for development, not for")
            print("an Acting-class secret on the server -- see docs/CREDENTIALS.md section 3.")
        else:
            resolution = credentials.put_keyring(args.ref, value)
            print(f"\nStored. fingerprint={resolution.fingerprint}  source={resolution.source}")
    except (credentials.CredentialError, OSError, ValueError) as e:
        print(f"Failed: {e}", file=sys.stderr)
        return 1
    finally:
        del value
    return 0


def cmd_encrypt(args) -> int:
    """Convert an already-stored plaintext credential into an encrypted one."""
    import config

    plain = config.SECRETS_DIR / args.ref
    if not plain.is_file():
        print(f"No plaintext credential at {plain}.", file=sys.stderr)
        return 1

    try:
        passphrase = _passphrase(confirm=True)
    except (ValueError, EOFError, KeyboardInterrupt) as e:
        print(f"\n{e or 'Cancelled.'}", file=sys.stderr)
        return 1

    value = plain.read_text(encoding="utf-8").strip()
    try:
        resolution = credentials.write_encrypted(
            args.ref, value, passphrase, label=args.label or "", overwrite=args.force
        )
    except credentials.CredentialError as e:
        print(f"Failed: {e}", file=sys.stderr)
        return 1
    finally:
        del value

    encrypted = config.SECRETS_DIR / (args.ref + credentials.ENCRYPTED_SUFFIX)
    print(f"Encrypted to {encrypted}. fingerprint={resolution.fingerprint}")

    # Verify BEFORE deleting the plaintext. An unreadable keystore plus a deleted
    # original is how you lose a credential during the migration meant to protect it.
    print("Verifying it reads back...")
    try:
        check = keystore.read(encrypted, passphrase)
        ok = credentials._fingerprint(check) == resolution.fingerprint
        del check
    except Exception as e:
        print(f"VERIFY FAILED: {e}", file=sys.stderr)
        print("The plaintext file was left in place.", file=sys.stderr)
        return 1
    finally:
        del passphrase

    if not ok:
        print("VERIFY FAILED: round-trip mismatch. Plaintext left in place.", file=sys.stderr)
        return 1
    print("  verified.")

    if args.keep:
        print(f"Plaintext kept at {plain} (--keep). Note it still wins the tier order.")
    else:
        plain.unlink()
        print(f"Removed the plaintext {plain}.")
    return 0


def cmd_passwd(_args) -> int:
    """Re-encrypt every keystore in the secrets directory under a new passphrase."""
    import config

    stores = sorted(config.SECRETS_DIR.glob("*" + credentials.ENCRYPTED_SUFFIX))
    if not stores:
        print("No encrypted credentials to re-key.")
        return 0

    print(f"Re-keying {len(stores)} keystore(s): {', '.join(x.name for x in stores)}")
    try:
        old = getpass("Current passphrase: ")
        new = getpass("New passphrase: ")
        if getpass("Confirm new passphrase: ") != new:
            print("Passphrases did not match.", file=sys.stderr)
            return 1
        if len(new) < 8:
            print("Passphrase must be at least 8 characters.", file=sys.stderr)
            return 1
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.", file=sys.stderr)
        return 1

    # All or nothing: every file must open with the old passphrase before any is
    # written, so a wrong passphrase cannot leave half the store on each key.
    try:
        values = {x: keystore.read(x, old) for x in stores}
    except keystore.KeystoreError as e:
        print(f"Failed: {e}", file=sys.stderr)
        print("Nothing was changed.", file=sys.stderr)
        return 1

    for path, value in values.items():
        keystore.write(path, value, new, label=keystore.label_of(path) or "", overwrite=True)
    values.clear()
    print(f"Re-keyed {len(stores)} keystore(s). Update {credentials.PASSPHRASE_ENV}.")
    return 0


def cmd_status(args) -> int:
    info = credentials.describe(args.ref)
    if not info["available"]:
        print(f"{args.ref}: NOT FOUND")
        print(f"  {info['error']}")
        return 1
    strength = "weak -- plaintext" if info["weak"] else "ok"
    print(f"{args.ref}: found")
    print(f"  source      : {info['source']} ({strength})")
    print(f"  fingerprint : {info['fingerprint']}")
    return 0


def cmd_rm(args) -> int:
    credentials.delete_keyring(args.ref)
    print(f"Removed '{args.ref}' from the OS keyring (if it was there).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage credentials for this app.")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, fn in (("set", cmd_set), ("status", cmd_status),
                     ("rm", cmd_rm), ("encrypt", cmd_encrypt)):
        p = sub.add_parser(name)
        p.add_argument("ref", help="the credential's name, e.g. session_secret")
        p.add_argument("--file", action="store_true",
                       help="write plaintext to the secrets directory")
        p.add_argument("--encrypted", action="store_true",
                       help="write an Argon2id/AES-256-GCM keystore; preferred for "
                            "anything the container must read")
        p.add_argument("--label", default="",
                       help="a non-secret identifier stored in the clear")
        p.add_argument("--force", action="store_true", help="overwrite an existing file")
        p.add_argument("--keep", action="store_true",
                       help="encrypt: leave the plaintext file in place")
        p.set_defaults(func=fn)

    sub.add_parser("passwd", help="re-key every keystore").set_defaults(func=cmd_passwd)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

""" EOF - credential.py """
