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


def _read(path: str) -> str:
    """A path, or "-" for stdin: the container cannot see the host's files, so
    `docker compose exec -T general-ledger python manage.py ... - < file.csv` works too."""
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def cmd_import_qbo_chart(args) -> int:
    from utils.errors import LedgerError
    from utils.migration import qbo_chart

    try:
        content = _read(args.path)
        if not args.apply:
            p = qbo_chart.preview(content)
            print(f"{p['qbo_accounts']} QuickBooks accounts -> {p['ledger_accounts']} ledger accounts "
                  f"({p['general_subaccounts']} '- General' sub-accounts added).\n")
            print(f"{'Number':<8}{'Type':<11}{'Bank':<6}Name   [QuickBooks name / type]")
            for a in p["accounts"]:
                indent = "    " if a["parent"] else ""
                origin = f"[{a['qbo_name']} / {a['qbo_type']}]" if a["qbo_name"] else "[added]"
                print(f"{a['number']:<8}{a['type']:<11}{'yes' if a['bank'] else '':<6}{indent}{a['name']}   {origin}")
            print("\nNothing written. Re-run with --apply to replace the chart.")
            return 0
        result = qbo_chart.apply(content)
    except (LedgerError, OSError) as e:
        print(f"Not imported: {e}", file=sys.stderr)
        return 1
    print(f"Chart replaced: {result['imported']} accounts in, {result['replaced']} removed.")
    return 0


def cmd_import_qbo_payees(args) -> int:
    from datetime import date

    from utils.errors import LedgerError
    from utils.migration import qbo_payees

    try:
        vendors, txns = _read(args.vendors), _read(args.transactions)
        since = date.fromisoformat(args.active_since)
        if not args.apply:
            planned, s = qbo_payees.plan(vendors, txns, since)
            print(f"{s['payees']} payees: {s['active']} active (used since {s['active_since']}), "
                  f"{s['archived']} archived ({s['never_used']} never on a transaction).")
            print(f"{s['vendors']} vendors, {s['customers']} customers; "
                  f"{s['with_default_account']} get a default account from history.")
            if s["unmapped_defaults"]:
                print(f"No default for these consistent-but-unknown accounts: {s['unmapped_defaults']}")
            print(f"\nActive payees:\n{'Last used':<12}{'Lines':>6}  {'Name':<42}Default account")
            for p in sorted((p for p in planned if p.is_active), key=lambda p: p.last_used, reverse=True):
                kind = ("V" if p.is_vendor else "") + ("C" if p.is_customer else "")
                print(f"{p.last_used.isoformat():<12}{p.lines:>6}  {(p.name + ' [' + kind + ']')[:40]:<42}"
                      f"{p.default_account or '-'}")
            print("\nNothing written. Re-run with --apply to import.")
            return 0
        s = qbo_payees.apply(vendors, txns, since, replace=args.replace)
    except (LedgerError, OSError, ValueError) as e:
        print(f"Not imported: {e}", file=sys.stderr)
        return 1
    print(f"Imported {s['payees']} payees: {s['active']} active, {s['archived']} archived, "
          f"{s['with_default_account']} with a default account.")
    return 0


def cmd_import_qbo_invoices(args) -> int:
    import json
    from datetime import date

    from utils.errors import LedgerError
    from utils.migration import qbo_invoices

    try:
        files = [_read(p) for p in (args.sales, args.payments, args.open, args.customers)]
        if not args.apply:
            print(json.dumps(qbo_invoices.preview(*files), indent=1))
            print("\nNothing written. Re-run with --apply to import.")
            return 0
        s = qbo_invoices.apply(*files, active_since=date.fromisoformat(args.active_since),
                               income_account_number=args.income_account, replace=args.replace)
    except (LedgerError, OSError, ValueError) as e:
        print(f"Not imported: {e}", file=sys.stderr)
        return 1
    print(f"Imported {s['invoices']} invoices ({s['lines']} lines, {s['customers']} customers); "
          f"open {s['open_total']}; next number {s['next_number']}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="General Ledger administration.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("set-password", help="set or change the owner password").set_defaults(
        func=cmd_set_password
    )
    qbo = sub.add_parser("import-qbo-chart",
                         help="replace the chart with a QuickBooks Online Account List CSV (empty books only)")
    qbo.add_argument("path", help="the CSV file, or - to read stdin")
    qbo.add_argument("--apply", action="store_true", help="write it; without this, only preview")
    qbo.set_defaults(func=cmd_import_qbo_chart)
    pay = sub.add_parser("import-qbo-payees",
                         help="payees from the QBO Vendor Contact List + Transaction Detail by Account CSVs")
    pay.add_argument("vendors", help="Vendor Contact List CSV")
    pay.add_argument("transactions", help="Transaction Detail by Account CSV (All Dates)")
    pay.add_argument("--active-since", default="2024-01-01",
                     help="payees last used before this are imported archived (default 2024-01-01)")
    pay.add_argument("--replace", action="store_true", help="replace existing, unreferenced payees")
    pay.add_argument("--apply", action="store_true", help="write it; without this, only preview")
    pay.set_defaults(func=cmd_import_qbo_payees)
    inv = sub.add_parser("import-qbo-invoices",
                         help="invoice history from QBO: Sales by Product/Service Detail, Invoices and "
                              "Received Payments, Open Invoices, Customer Contact List (CSV)")
    inv.add_argument("sales")
    inv.add_argument("payments")
    inv.add_argument("open")
    inv.add_argument("customers")
    inv.add_argument("--income-account", help="account number for invoice lines (default: Website Hosting)")
    inv.add_argument("--active-since", default="2024-01-01",
                     help="customers invoiced or paying since this are active (default 2024-01-01)")
    inv.add_argument("--replace", action="store_true", help="replace previously imported QBO invoices")
    inv.add_argument("--apply", action="store_true", help="write it; without this, only preview")
    inv.set_defaults(func=cmd_import_qbo_invoices)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

""" EOF - manage.py """
