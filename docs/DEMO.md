<!-- General Ledger v0.6.1 | File: docs/DEMO.md -->
# Demo data

A made-up company, **Bluebird Design Studio LLC**, with three months of activity, built
through the app's own code paths (`utils/demo.py`): customers and invoices issued, Chase-style
CSVs imported, lines posted by accepting suggestions or choosing an account with Remember,
card payments paired as transfers, deposits paying invoices. What is left shows the rest:
the last 12 days wait in Banking -> Review, one invoice is overdue, one is a draft, and the
first month is locked.

## Run it

```
python3 scripts/dev_init.py
```

```
docker compose -f compose.dev.yml up --build
```

Open http://127.0.0.1:8001 and sign in with **bluebird-demo**.

`docker/dev-initdb/02-demo.sql` loads the demo on the database's first start (an empty
volume). Its dates are fixed at 2026-07-01 to 2026-10-01. To start over:

```
docker compose -f compose.dev.yml down -v
```

To start with an empty ledger instead, delete `docker/dev-initdb/02-demo.sql` before the
first `up`.

## Make a fresh one (dates up to today)

Into an empty, migrated database (refused if it has entries):

```
docker compose -f compose.dev.yml run --rm general-ledger python manage.py make-demo
```

```
docker compose -f compose.dev.yml run --rm general-ledger python manage.py set-password
```

<!-- EOF - docs/DEMO.md -->
