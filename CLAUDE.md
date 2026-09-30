# General Ledger

Single-company, double-entry general ledger replacing QuickBooks Online for a small
service business. Chase checking and card come in through a bank feed (Plaid), become
journal entries through a review queue, and produce the reports an accountant needs.
Flask + MySQL 8.0, deployed to the Photon stack.

**Read first:** `docs/DESIGN.md` (this app), `docs/NEW-APP-INTEGRATION.md` (deployment
and container contract — binding), `docs/STYLING.md` (UI — binding),
`docs/CREDENTIALS.md` (secrets — binding), `PLAID_PLAN.md` (the Plaid integration),
`docs/BACKLOG.md` (deferred and later work).

Everything in `docs/` except `DESIGN.md` and `BACKLOG.md` is a **synced copy** from `_standards/docs/`;
`docs/.standards-version` records which revision. Do not edit them here — change the
canonical copy and run `python sync.py push general-ledger` from `_standards/`.
Project-specific notes go in their own file.

## Names

`general-ledger` is the repo, service, container and hostname. `gl` is the MySQL
database and user. `/data` is the data mount, `/etc/general-ledger` the secrets mount.
Browser tabs read `Ledger - <Page>`.

## Local development

```bash
python scripts/dev_init.py                          # once: .devdata, .devsecrets, dev session key
docker compose -f compose.dev.yml up --build        # app on 127.0.0.1:8001, MySQL on 3308
docker compose -f compose.dev.yml run --rm general-ledger python manage.py set-password
docker compose -f compose.dev.yml down -v           # reset the database completely

python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest                      # against gl_test in the dev MySQL
```

Ports 3308/8001 so this runs alongside trade-portfolio's dev stack (3307/8000).
There is **one Dockerfile and no dev variant**. Tests run against MySQL only.

## Build order (docs/DESIGN.md section 13)

Phases 0 (skeleton) and 1 (core ledger) are done, and phase 2a: Chase **CSV** import
(QFX deliberately not supported: it truncates descriptions and its checking FITID is
just date + sequence) and the review queue; the QuickBooks chart and payees are imported
(`manage.py import-qbo-chart`, `import-qbo-payees`); phase 2b: suggestions
(`utils/suggest.py`: transfer > rule > active payee > history, recomputed from scratch
after every change), payee rules and "Remember", transfers posted as one entry, "Post
all suggested"; receipts; the type-to-search account picker. Invoicing was moved ahead of
phase 3 by the owner (2026-09-30): step A is done (tables, `manage.py import-qbo-invoices`
history with payments matched oldest-first, Invoices / Customers / A/R Aging pages). QuickBooks
history never posts: its income reaches this ledger once, through the opening balances.
Next: invoicing step B (create, issue, void, PDF, deposits suggesting the invoice they pay),
then phase 3. Keyboard shortcuts are deferred (docs/BACKLOG.md).
Plaid is phase 4 and its decisions are already settled in `PLAID_PLAN.md`.

Real Chase downloads live in `.bankdata/` (gitignored — real account data, never
committed). Tests use the synthetic look-alikes in `tests/fixtures/`.

Migration 0002 installs the DESIGN.md 3.2a triggers (plus two on `journal_entry`). On
the server they need `log_bin_trust_function_creators=1` on the shared `db` service —
an infra-side change to request before the first deploy. If it is declined, remove the
TRIGGERS from that migration; nothing else depends on them.

## Architecture rules (see docs/DESIGN.md)

- 🚨 **The web process never calls Plaid, SMTP or anything external**, with exactly two
  stated exceptions: `POST /api/connections/link-token` and `POST /api/connections/exchange`
  (interactive Link). Everything else is a row the worker polls (`sync_requested_at`,
  `email_requested_at`).
- 🚨 **Money is `DECIMAL(14,2)` and Python `Decimal` end to end, stored signed in one
  column: debit positive, credit negative.** Never float. Every entry sums to exactly 0.
- 🚨 **`post_entry()` in `utils/journal.py` is the only code path that inserts
  `journal_line` rows.** A posted entry is never updated or deleted; corrections are
  reversals. Only memo and attachments may change, with an `audit_log` row.
- 🚨 **Nothing is posted on or before the lock date**, including reversals.
- 🚨 **Amounts cross the API as strings** ("49.00"), parsed by `utils/money.py`; a JSON
  number is refused, so no float ever reaches a figure.
- Functions in `utils/journal.py` that take a `session` never commit; the caller owns the
  transaction (that is what makes Edit = reverse + re-post atomic).
- Business errors raise `LedgerError` (utils/errors.py); `routes/api.py`'s `@envelope`
  turns them into a 400 and anything else into a logged 500.
- **Rules and matching only suggest.** Only a human moves a bank line to POSTED or EXCLUDED.
- Accounting dates are `DATE` (no time zone). Audit timestamps are UTC `DATETIME(6)`.
  `TZ` is for log readability only.
- Bank-feed sign normalisation happens in exactly one place per connector (`normalise()`).
- The integrity check reports; it never repairs.
- Migrations run from the entrypoint, once, serialized by `GET_LOCK('general-ledger-migrate')`.
- The worker holds `GET_LOCK('general-ledger-worker')` and stops if it loses it.
- No inbound webhooks; the feed is polled daily (decision recorded in `PLAID_PLAN.md`).

## Plaid (see PLAID_PLAN.md)

This integration is maintained with the Plaid MCP. Consult its build guidance before
changing any Plaid-touching code, and re-run its acceptance check before reporting such
a change as working.

## Login (docs/DESIGN.md section 11)

- One owner. Argon2id hash in `settings.owner_password_hash`, set only by
  `manage.py set-password` — never by a web form. Changing it signs out every session.
- Session cookie `gl_session`: HttpOnly, SameSite=Strict, Secure when `APP_HTTPS=1`,
  12 hours idle. Signed with the `session_secret` credential.
- Every non-GET request must be `application/json` (the CSRF defence); `api()` always is.
- `/healthz` and `/login` are the only public routes.

## UI Styling (see docs/STYLING.md - binding)

- All pages extend `templates/base.html`; the only stylesheet is `static/css/dashboard.css`,
  shared JS is `static/js/dashboard.js`. Do not copy header/nav markup or base CSS into pages.
- Look: white `.section` cards on #f8f9fa, system font, one blue (#007bff). Color is
  semantic only (blue = primary/active, green/red = positive/negative, pale tints = status).
  No gradients, no dark panels, no new accent colors.
- TAB TITLES: every `<title>` is `Ledger - <Page Name>` - prefix first, same on every
  page (utility/OAuth pages too), set once as `config.APP_TITLE_PREFIX` and applied by
  base.html. `tests/test_page_titles.py` enforces it.
- 🚨 TOP NAV: never add a top-nav entry (NAV_ITEMS in app.py) without explicit permission.
  Sibling pages use the `.sub-menu`; in-page panels use `.tabs`. The six items of
  DESIGN.md 12.1 were approved on 2026-09-29. Sub-menus are defined once in `SUB_MENUS`
  (app.py) and rendered by base.html; pages set `active_sub`.
- 🚨 NO FALLBACKS: never write `value || 0` or estimate a missing backend value in the
  frontend. Missing data must look broken. Intentional absence comes from the server as
  null and renders as an em dash.
- The server computes all figures; the page only formats them.
- API envelope: `{success: true, ...}` / `{success: false, error}`. Use the `api()` helper.
- Tables: numbers right-aligned (`.num`), explicit Loading/empty/error row, `.btn.small` row
  actions. Escape server data with `escapeHtml()` before putting it in innerHTML.
- Async buttons use `setBusy()`; refreshes report partial results as partial and never
  clear on-screen data on error.
- 🚨 WIZARDS: Back (gray, left, hidden on step 1) | Cancel (`.btn.danger`, always red) +
  Next/Submit (rightmost, blue/green), grouped on the right.
- Every file has a version header comment and an EOF marker.

## Secrets (see docs/CREDENTIALS.md - binding)

- The database and repo store a credential's NAME (`credential_ref`), never its value.
- Resolve through `utils/credentials.py`, which tries OS keyring, then encrypted file,
  then plain file/env, and warns on the last. Never read a secret path directly.
- 🚨 Never log, print or echo a secret. Use `credentials.describe()`, which returns a
  SHA-256 fingerprint, when you need to confirm which credential is loaded.
- Containers have no OS keyring - that is why the encrypted-file tier exists.
- Plaid access tokens and API keys are tier 2 (encrypted) in production; Plaid tokens
  are never logged — log `request_id` instead.
- Gitignore a secret path before creating the file. A committed secret is rotated,
  not deleted.

<!-- EOF - CLAUDE.md -->
