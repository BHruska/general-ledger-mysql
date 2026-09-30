#!/usr/bin/env python3
"""
General Ledger v0.6.1
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
        before = date.fromisoformat(args.before) if args.before else None
        if not args.apply:
            print(json.dumps(qbo_invoices.preview(*files, before=before), indent=1))
            print("\nNothing written. Re-run with --apply to import.")
            return 0
        s = qbo_invoices.apply(*files, active_since=date.fromisoformat(args.active_since),
                               income_account_number=args.income_account, replace=args.replace, before=before)
    except (LedgerError, OSError, ValueError) as e:
        print(f"Not imported: {e}", file=sys.stderr)
        return 1
    print(f"Imported {s['invoices']} invoices ({s['lines']} lines, {s['customers']} customers); "
          f"open {s['open_total']}; next number {s['next_number']}.")
    return 0


def cmd_import_qbo_journal(args) -> int:
    import json
    from datetime import date

    from utils.errors import LedgerError
    from utils.migration import qbo_journal

    try:
        content, before = _read(args.path), date.fromisoformat(args.before)
        if not args.apply:
            print(json.dumps(qbo_journal.preview(content, before), indent=1))
            print("\nNothing written. Re-run with --apply to import.")
            return 0
        s = qbo_journal.apply(content, before)
    except (LedgerError, OSError, ValueError) as e:
        print(f"Not imported: {e}", file=sys.stderr)
        return 1
    print(f"Imported {s['transactions']} QuickBooks transactions ({s['lines']} lines), "
          f"{s['first_date']} to {s['last_date']}; {s['invoices_linked']} invoices linked; "
          f"books locked through {s['lock_date']}.")
    return 0


def cmd_rebuild_from_qbo(args) -> int:
    import json
    from datetime import date, datetime
    from pathlib import Path

    from utils.errors import LedgerError
    from utils.migration import rebuild

    try:
        before = date.fromisoformat(args.before)
        feeds = []
        for spec in args.feed:
            # "=" rather than ":" as the separator, so a Windows drive letter stays in the path.
            bits = spec.split("=")
            if len(bits) not in (2, 3) or not bits[0] or not bits[1]:
                raise LedgerError("--feed is PATH=ACCOUNT_NUMBER[=MASK], e.g. .bankdata/Chase1234.csv=1010=1234")
            feeds.append((Path(bits[0]), bits[1], bits[2] if len(bits) > 2 else None))
        learning = None
        if args.keep_learning:
            learning = rebuild.save_learning()
            backup = Path(args.qbo_dir).parent / f"learning-{datetime.now():%Y%m%d-%H%M%S}.json"
            backup.write_text(json.dumps(learning, indent=1, default=str), encoding="utf-8")
            print(f"Saved {len(learning['rules'])} rules and {len(learning['payees'])} payees to {backup}.")
        if args.reset_dev_database:
            rebuild.reset_dev_database()
            print("Dev database emptied (login kept).")
        result = rebuild.rebuild(Path(args.qbo_dir), before, feeds, learning=learning,
                                 active_since=date.fromisoformat(args.active_since))
    except (LedgerError, OSError, ValueError) as e:
        print(f"Rebuild stopped: {e}", file=sys.stderr)
        return 1
    h = result["history"]
    print(f"\nHistory: {h['transactions']} transactions {h['first_date']} to {h['last_date']}; locked through {h['lock_date']}.")
    for f in result["feeds"]:
        print(f"Feed: {f['file']} -> {f['account']}: {f['lines']} lines.")
        g = f["gaps"]
        if not g["not_in_history"] and not g["not_in_chase"]:
            print(f"  Chase and QuickBooks agree from {g['checked_from']} to the boundary.")
            continue
        print(f"  Chase and QuickBooks DISAGREE between {g['checked_from']} and the boundary"
              " -- fix these in QuickBooks, re-export the Journal and rebuild:")
        for m in g["not_in_history"]:
            print(f"    in Chase, not in QuickBooks:  {m['date']} {m['amount']:>10}  {m['description']}")
        for m in g["not_in_chase"]:
            print(f"    in QuickBooks, not in Chase:  {m['date']} {m['amount']:>10}  {m['memo']}")
    if result["learning"]:
        l = result["learning"]
        print(f"Restored {l['rules']} rules and {l['payees']} payees; suggestions: {l['suggestions']['by_reason']}.")
        for u in l["unresolved"]:
            print(f"  not restored: {u}")
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
    inv.add_argument("--before", help="boundary date (YYYY-MM-DD): history stops here; later invoices and "
                                      "payments belong to this ledger's own postings")
    inv.add_argument("--apply", action="store_true", help="write it; without this, only preview")
    inv.set_defaults(func=cmd_import_qbo_invoices)
    jrn = sub.add_parser("import-qbo-journal",
                         help="QuickBooks history before a boundary date, from the QBO Journal report (CSV)")
    jrn.add_argument("path", help="Journal report CSV (All Dates), or - for stdin")
    jrn.add_argument("--before", required=True,
                     help="boundary date (YYYY-MM-DD): the bank feed's start; later transactions are skipped")
    jrn.add_argument("--apply", action="store_true", help="write it; without this, only preview")
    jrn.set_defaults(func=cmd_import_qbo_journal)
    reb = sub.add_parser("rebuild-from-qbo",
                         help="rebuild the books from the QuickBooks exports and Chase CSVs")
    reb.add_argument("--qbo-dir", required=True, help="folder holding the QuickBooks CSV exports")
    reb.add_argument("--before", required=True, help="boundary date: QuickBooks history before it, Chase from it")
    reb.add_argument("--feed", action="append", default=[],
                     help="PATH=ACCOUNT_NUMBER[=MASK], once per Chase CSV, e.g. .bankdata/Chase1234.csv=1010=1234")
    reb.add_argument("--keep-learning", action="store_true",
                     help="save rules, payee edits and settings first and restore them after")
    reb.add_argument("--reset-dev-database", action="store_true",
                     help="empty the LOCAL dev database first (keeps the login); refused anywhere else")
    reb.add_argument("--active-since", default="2024-01-01")
    reb.set_defaults(func=cmd_rebuild_from_qbo)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

""" EOF - manage.py """
