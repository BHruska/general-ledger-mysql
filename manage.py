#!/usr/bin/env python3
"""
General Ledger v0.1.0
File: manage.py
Description: Owner administration that must not be a web page.

    docker compose -f compose.dev.yml run --rm general-ledger python manage.py set-password

set-password is a CLI rather than a first-run web form on purpose: a form that sets the
owner password while none exists would hand the books to whoever reached it first --
and everyone past the shared nginx password can reach it.
"""

import argparse
import sys
from getpass import getpass

import config


def cmd_set_password(_args) -> int:
    from utils import auth

    print(f"Setting the owner password (at least {config.MIN_PASSWORD_LENGTH} characters).")
    print("Every existing session is signed out when it changes.")
    try:
        password = getpass("New password: ")
        if getpass("Confirm: ") != password:
            print("Passwords did not match; nothing changed.", file=sys.stderr)
            return 1
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.", file=sys.stderr)
        return 1

    try:
        auth.set_password(password)
    except auth.AuthError as e:
        print(f"Not changed: {e}", file=sys.stderr)
        return 1
    finally:
        del password
    print("Owner password set.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="General Ledger administration.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("set-password", help="set or change the owner password").set_defaults(
        func=cmd_set_password
    )
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

""" EOF - manage.py """
