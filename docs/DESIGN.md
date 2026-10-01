# General Ledger — Design

**Revision 1 — 2026-09-28.**

A single-company, double-entry general ledger to replace a QuickBooks Online
subscription for a small service business. Almost every expense arrives through a
Chase credit card or an ACH debit from Chase checking, and almost every invoice is a
few lines that the customer pays by Zelle. The app pulls both Chase accounts in through a
bank-feed connector (Plaid by default), turns each bank line into a journal entry through
a review queue and payee rules, issues invoices, and produces the reports an accountant
and a tax return need.

This document assumes [NEW-APP-INTEGRATION.md](NEW-APP-INTEGRATION.md),
[STYLING.md](STYLING.md) and [CREDENTIALS.md](CREDENTIALS.md), and does not repeat
them. Where this document is silent on deployment, containers, or the database
engine, the integration doc governs. Where it is silent on look or frontend
behaviour, the styling doc governs. Where it is silent on secrets, the credentials
doc governs.

---

## 0. Names

| Thing | Value |
| --- | --- |
| Repo, service, container | `general-ledger` |
| Public hostname | `general-ledger.hruskagroup.com` |
| MySQL database and user | `gl` |
| Data directory | `/opt/data/general-ledger` → `/data` (invoice PDFs, receipt attachments) |
| Secrets mount | `/opt/data/secrets/general-ledger` → `/etc/general-ledger` |
| Gunicorn target | `wsgi:app` |
| Worker | `python -m worker` |
| Make targets | `up-gl`, `logs-gl`, `redeploy-gl` |
| Browser tab prefix | `Ledger` → `Ledger - Bank Review` |

### 0.1 Local development: its own MySQL

Development runs against a **dedicated MySQL 8.0 container** in this repo's
`compose.dev.yml`, as the integration doc prescribes. It is a separate Compose project
(`name: general-ledger-dev`) with its own named volume (`general-ledger-dev-mysql`),
its own databases (`gl` and `gl_test`) and its own user (`gl`). It shares nothing with
the portfolio or trading apps' databases, and `docker compose -f compose.dev.yml down -v`
here cannot touch them.

Host ports are chosen so it runs alongside `trade-portfolio`'s dev stack, which holds
3307 and 8000:

| | Host port | Container port |
| --- | --- | --- |
| MySQL | `127.0.0.1:3308` | 3306 |
| App | `127.0.0.1:8001` | 8000 |

The dev MySQL service also sets `command: --log-bin-trust-function-creators=1` to
match production if the triggers in §3.2a are adopted.

In production the same isolation holds: its own `gl` database and `gl` user, granted
on `gl.*` only, on the shared server. A leaked credential from any other app cannot
read the books, and this app's credentials cannot read theirs.

### 0.2 Layout

The flat layout from [STYLING.md §7](STYLING.md) (`app.py`, `routes/`, `utils/`) with a
root `wsgi.py` and `worker.py`, exactly as `trade-portfolio` resolved the same
conflict with the integration doc's package-style entrypoint.

---

## 1. Scope

### 1.1 What it does

| Area | In scope |
| --- | --- |
| Chart of accounts | five account types, sub-accounts one level deep, a tax-line mapping per account |
| Journal | double-entry entries, posted and immutable, corrected by reversal |
| Bank feeds | File import is primary: Chase CSV, plus OFX/QFX/QBO for other banks. An automatic feed (SimpleFIN, or Plaid) is optional and deferred (§5.3) |
| Review queue | every bank line becomes a journal entry only after it is categorised, matched or excluded |
| Payee rules | "description contains X → account Y", applied as suggestions, learned from what you post |
| Transfers | a card payment seen on both feeds is posted once |
| Invoicing | customers, simple invoices, PDF by email, Zelle payment instructions, open-invoice matching |
| Reconciliation | monthly statement reconciliation per bank or card account |
| Receipts | file attachments on any journal entry |
| Reports | P&L, balance sheet, trial balance, general ledger detail, account register, A/R aging, tax-line summary, 1099 vendor totals |
| Period control | a lock date; nothing on or before it can be posted, edited or reversed |
| Migration | opening balances and open invoices from QuickBooks at a cutover date |

### 1.2 What it deliberately does not do

Each of these is a QuickBooks feature that a business shaped like this one does not use.
Leaving them out keeps the schema small enough to trust.

| Not built | Why not |
| --- | --- |
| Accounts payable (bills, bill pay) | Bills are paid by card or ACH the moment they are due. The bank line *is* the bill. |
| Payroll | Use a payroll service; post its summary journal entry monthly. |
| Inventory, items with quantities | A service business. Invoice lines are description, quantity and rate. |
| Multi-currency, multi-company | One company, US dollars. |
| Sales tax | Services; add a liability account and a line flag if that ever changes. |
| Classes, locations, projects | One business line. The account tree is the only dimension. |
| Online invoice portal, card payments | The app sits behind nginx Basic Auth ([NEW-APP-INTEGRATION.md §6](NEW-APP-INTEGRATION.md)); customers can never reach it. Invoices go out as PDF email and are paid by Zelle. |
| Budgets, forecasting | Can be a report later; no schema needed now. |
| Multiple users with roles | One owner login (§11). An accountant gets exported reports, not a login. |

### 1.3 Accounting basis

**Accrual for revenue, cash for everything else.** An invoice posts to Accounts
Receivable when issued; expenses post when the bank or card line appears. That gives an
accurate A/R aging (the one accrual report this business needs) without an A/P
module. The P&L can be run on either basis (§9.2), because the cash-basis view is just
"income recognised on payment date" and is derivable from the same journal.

---

## 2. Shape

Two Compose services built from **one image**, selected by `command:`, per the
integration doc's default.

```
general-ledger          gunicorn, 2 workers x 4 threads     <- nginx proxies here
general-ledger-worker   feed sync, rule application, invoice email, integrity check
```

**The worker owns every scheduled external call.** Daily feed sync, the "Sync now"
button, and sending invoice emails are all row writes that the worker polls
(`bank_connection.sync_requested_at`, `invoice.email_requested_at`) — the
`desired_state` pattern from [NEW-APP-INTEGRATION.md §3](NEW-APP-INTEGRATION.md).
A Plaid outage then makes the feed stale; it never makes a page fail to load.

**One exception, stated rather than hidden:** linking or re-linking a bank through Plaid
Link is interactive. The browser needs a `link_token` created on the spot, and the
`public_token` Link returns expires in 30 minutes. So two web routes call Plaid
synchronously: `POST /api/connections/link-token` and
`POST /api/connections/exchange`. Each is a single call that returns in about a second,
well inside the 30-second ceiling. Nothing else in the web process talks to Plaid.

### 2.1 Worker schedule

| Job | When | Notes |
| --- | --- | --- |
| Feed sync | 06:00 Central daily, and within 15 s of a "Sync now" row write | per connection; §5 |
| Apply rules | after each sync | suggestions only; never posts (§6.2) |
| Send invoice email | within 15 s of a request row | §8.3 |
| Integrity check | 02:00 Central daily | §3.5; writes a `health_finding` row, never repairs |
| Prune | weekly | `feed_sync_log` older than 180 days |

The worker holds `SELECT GET_LOCK('general-ledger-worker', 0)` on a dedicated connection
and does nothing without it ([NEW-APP-INTEGRATION.md §5](NEW-APP-INTEGRATION.md), one
writer per account). Two workers syncing the same Plaid item would each insert the same
bank lines; the unique key in §4 would stop the duplicates, but the lock stops the race.

---

## 3. The accounting core

This is the part that has to be right. Everything else is convenience around it.

### 3.1 Journal entries and lines

Every financial event is one `journal_entry` with two or more `journal_line` rows.

**Amounts are stored signed in one column: debit positive, credit negative.**
`DECIMAL(14,2)`, Python `Decimal` end to end. The UI shows separate Debit and Credit
columns; the database never does.

Why one signed column rather than a debit column and a credit column:

- The balancing rule becomes `SUM(amount) = 0` per entry, and a trial balance becomes
  `SUM(amount)` over everything. Both are one aggregate with no `CASE`.
- There is no representable row with both a debit and a credit, or with neither, so an
  entire class of validation disappears.
- An account's balance in its *normal* direction is `SUM(amount) × normal_sign`
  (`+1` for assets and expenses, `−1` for liabilities, equity and income). That sign
  lives on the account type (§3.3) and nowhere else.

The balancing invariant is enforced **in the service layer** (`utils/journal.py`).
It cannot be a trigger: MySQL triggers are row-level, lines arrive one insert at a
time, and MySQL has no deferred or statement-level check, so every entry is out of
balance until its last line lands. Triggers do earn a place for the rules that *can*
be checked one row at a time (§3.2a). `post_entry()` is the only code path that inserts
`journal_line` rows, and it refuses an entry that:

- has fewer than two lines;
- does not sum to exactly `0.00`;
- has a zero-amount line;
- touches an inactive account, or a header account that has children (§3.3);
- is dated on or before the lock date (§3.4);
- has a line on a bank or card account without a `bank_txn` link when the entry came
  from the review queue (so a bank line cannot be posted twice; §6).

A test inserts entries through every public path and asserts the global sum is zero
afterwards. The daily integrity check (§3.5) asserts it against production.

### 3.2 Posted means immutable

There is no draft journal entry. An entry exists only once it is balanced and posted.
Drafts live where they belong — in the review queue (an unposted `bank_txn`) and in
draft invoices — and become journal entries in one transaction.

**A posted entry is never updated or deleted.** Correcting one writes a reversing entry
(every line negated, `reverses_entry_id` set, same or later date) and, usually, a new
correct entry. The UI offers this as a single "Edit" that performs *reverse and
re-post* in one transaction, so it feels like editing while leaving the audit trail
intact. Both entries show in the general ledger detail report, linked.

This is the rule you would have enforced on an insurance agency ledger for the same
reason: the books must be explainable to an auditor from the rows alone.

The one exception is **memo and attachment**: descriptive fields on a posted entry can
be edited, and each change writes an `audit_log` row. They change no amount, date or
account.

### 3.2a Triggers as a backstop

The integration doc says "no stored functions or triggers **without a real need**"
([§2](NEW-APP-INTEGRATION.md)). That is a caution, not a ban, and the reason is
operational: with binary logging on (the MySQL 8.0 default), a user without `SUPER`
can create a trigger only if the server has `log_bin_trust_function_creators = 1`.
That is a global setting, so it is an infra-side change to the shared `db` service,
and it has to be mirrored in `compose.dev.yml` (`command:
--log-bin-trust-function-creators=1`) so dev and prod behave alike.

The real need here: the books must stay immutable even against someone editing rows
in phpMyAdmin or an ad-hoc SQL session, where no Python code runs. So, three small
triggers, created by an Alembic migration:

| Trigger | Refuses |
| --- | --- |
| `journal_line` BEFORE UPDATE | any change to `entry_id`, `account_id`, `amount` or `line_no` (only `memo` and `cleared_recon_id` may change) |
| `journal_line` BEFORE DELETE | every delete |
| `journal_line` BEFORE INSERT | a line whose entry date is on or before `settings.lock_date`, or an amount of `0.00` |

Each raises `SIGNAL SQLSTATE '45000'` with a message naming the rule. Python still checks
the same rules first, so a user sees a readable error rather than a database exception;
the triggers only catch what bypasses the app. Tests assert that each one fires.

If the infra side declines the global setting, drop the triggers and nothing else
changes. The service layer and the nightly integrity check (§3.5) still hold every
rule; only the phpMyAdmin backstop is lost.

### 3.3 Chart of accounts

```
account
  id, number (e.g. '1010'), name, type, parent_id, is_active,
  is_bank_account, tax_line, is_1099_expense, description
```

| Type | Normal sign | Number range | Examples |
| --- | --- | --- | --- |
| `ASSET` | +1 (debit) | 1000–1999 | 1010 Chase Checking, 1200 Accounts Receivable |
| `LIABILITY` | −1 (credit) | 2000–2999 | 2010 Chase Ink Card, 2200 Owner loan |
| `EQUITY` | −1 (credit) | 3000–3999 | 3000 Owner's Equity, 3100 Owner Draws, 3900 Retained Earnings |
| `INCOME` | −1 (credit) | 4000–4999 | 4000 Consulting Revenue |
| `EXPENSE` | +1 (debit) | 5000–7999 | 6100 Software Subscriptions, 6300 Travel |

- **Sub-accounts one level deep.** `6100 Software` can have `6110 Hosting`,
  `6120 SaaS`. A parent with children is a header: it rolls up in reports but cannot
  take a posting. Deeper trees add complexity and no information at this size.
- **Account numbers are the sort key** in every report, so the order is yours rather
  than alphabetical.
- **`tax_line`** maps each income and expense account to a line of the return
  (Schedule C line 18 *Office expense*, line 24a *Travel*, or the 1120-S / 1065
  equivalent). The tax summary report (§9) groups by it, which is most of what an
  accountant asks for at year end.
- **`is_bank_account`** marks the accounts a feed can post to. Each is linked from
  exactly one `bank_account` row (§5).
- An account with postings cannot be deleted, only deactivated. An inactive account
  still appears in historical reports.

A seed migration creates a small default chart; the migration from QuickBooks (§10)
replaces it with the real one.

### 3.4 Periods and the lock date

There is no period table and no closing entry.

- **Fiscal year** is a setting (default January). Reports take any date range.
- **Retained earnings are computed, not posted.** The balance sheet at date *D* shows
  `3900 Retained Earnings` as its own postings (the opening entry, §10) plus all income
  and expense before the start of *D*'s fiscal year, and "Net income, current year" as
  income and expense from that start to *D*.
  No closing entry means nothing to forget and nothing to re-run when a prior-year
  entry changes.
- **The lock date** (`settings.lock_date`) is the only close. `post_entry()` refuses
  any date on or before it, including reversals. Set it after the accountant has the
  year-end numbers; moving it backwards is allowed but asks for a reason, which goes to
  `audit_log`.

### 3.5 Integrity check

Nightly, the worker verifies and records findings. It never repairs anything, for the
same reason `trade-portfolio` never auto-corrects drift: a repaired inconsistency
destroys the evidence of what caused it.

| Check | Finding if it fails |
| --- | --- |
| Every entry sums to zero | entry id, its sum |
| The whole journal sums to zero | the global sum |
| Every posted `bank_txn` links to exactly one entry that touches its bank account for its amount | bank_txn id |
| Every bank account's GL balance matches the balance Plaid last reported, after uncleared items | account, both figures, difference |
| No posting on or before the lock date since the lock date was set | entry id |
| Invoice balances agree with A/R: sum of open invoice balances = 1200 A/R balance | both figures |

Findings show as a count on the Dashboard and a list on the Setup → Health page.

---

## 4. Schema

MySQL 8.0, database `gl`, Alembic-owned. `DECIMAL(14,2)` for money, `DATE` for
accounting dates (a posting date has no time zone and must never shift), UTC
`DATETIME(6)` for every audit timestamp. Indexes declared in `CREATE TABLE` or by
Alembic, never by a bare `CREATE INDEX` ([NEW-APP-INTEGRATION.md §2](NEW-APP-INTEGRATION.md)).

```sql
CREATE TABLE account (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  number          VARCHAR(10)  NOT NULL,
  name            VARCHAR(100) NOT NULL,
  type            ENUM('ASSET','LIABILITY','EQUITY','INCOME','EXPENSE') NOT NULL,
  parent_id       INT NULL,
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,
  is_bank_account BOOLEAN NOT NULL DEFAULT FALSE,
  tax_line        VARCHAR(60) NULL,          -- e.g. 'SCH_C_18_OFFICE'
  is_1099_expense BOOLEAN NOT NULL DEFAULT FALSE,
  description     VARCHAR(255) NULL,
  UNIQUE KEY uq_account_number (number),
  FOREIGN KEY (parent_id) REFERENCES account(id)
);

CREATE TABLE payee (                          -- vendors and customers share one table
  id              INT AUTO_INCREMENT PRIMARY KEY,
  name            VARCHAR(120) NOT NULL,
  is_customer     BOOLEAN NOT NULL DEFAULT FALSE,
  is_vendor       BOOLEAN NOT NULL DEFAULT FALSE,
  email           VARCHAR(255) NULL,          -- invoice recipient
  address         TEXT NULL,                  -- printed on invoices
  default_account_id INT NULL,                -- expense or income account
  is_1099_vendor  BOOLEAN NOT NULL DEFAULT FALSE,
  tax_id_ref      VARCHAR(60) NULL,           -- a credential_ref, never the TIN itself (§11)
  payment_terms_days INT NOT NULL DEFAULT 15,
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,
  UNIQUE KEY uq_payee_name (name),
  FOREIGN KEY (default_account_id) REFERENCES account(id)
);

CREATE TABLE journal_entry (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  entry_date      DATE NOT NULL,
  memo            VARCHAR(255) NULL,
  source          ENUM('MANUAL','BANK','INVOICE','PAYMENT','OPENING','REVERSAL','IMPORT') NOT NULL,
  payee_id        INT NULL,
  reverses_entry_id BIGINT NULL,              -- set on a reversal
  reversed_by_entry_id BIGINT NULL,           -- set on the original when reversed
  created_at      DATETIME(6) NOT NULL,
  KEY ix_entry_date (entry_date),
  FOREIGN KEY (payee_id) REFERENCES payee(id),
  FOREIGN KEY (reverses_entry_id) REFERENCES journal_entry(id)
);

CREATE TABLE journal_line (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  entry_id        BIGINT NOT NULL,
  line_no         SMALLINT NOT NULL,
  account_id      INT NOT NULL,
  amount          DECIMAL(14,2) NOT NULL,     -- debit +, credit -; never 0
  memo            VARCHAR(255) NULL,
  cleared_recon_id INT NULL,                  -- set when reconciled (§7)
  UNIQUE KEY uq_line (entry_id, line_no),
  KEY ix_line_account (account_id, entry_id),
  FOREIGN KEY (entry_id) REFERENCES journal_entry(id),
  FOREIGN KEY (account_id) REFERENCES account(id)
);

CREATE TABLE bank_connection (                -- one Plaid Item, or one SimpleFIN access URL
  id              INT AUTO_INCREMENT PRIMARY KEY,
  provider        ENUM('PLAID','SIMPLEFIN','FILE') NOT NULL,
  institution     VARCHAR(100) NOT NULL,      -- 'Chase'
  credential_ref  VARCHAR(60) NULL,           -- name of the access token, never the token
  provider_item_id VARCHAR(100) NULL,         -- Plaid item_id
  sync_cursor     TEXT NULL,                  -- Plaid /transactions/sync cursor
  status          ENUM('OK','LOGIN_REQUIRED','ERROR','DISCONNECTED') NOT NULL DEFAULT 'OK',
  status_detail   VARCHAR(255) NULL,
  consent_expires_at DATETIME(6) NULL,        -- Chase makes the user pick a duration
  last_synced_at  DATETIME(6) NULL,
  sync_requested_at DATETIME(6) NULL          -- "Sync now"; the worker polls this
);

CREATE TABLE bank_account (                   -- one feed account = one GL bank account
  id              INT AUTO_INCREMENT PRIMARY KEY,
  connection_id   INT NOT NULL,
  gl_account_id   INT NOT NULL,
  provider_account_id VARCHAR(100) NULL,      -- Plaid account_id
  kind            ENUM('DEPOSITORY','CREDIT') NOT NULL,
  mask            VARCHAR(8) NULL,            -- last 4, for display
  name            VARCHAR(100) NOT NULL,
  feed_start_date DATE NOT NULL,              -- lines before this are ignored (§10)
  reported_balance DECIMAL(14,2) NULL,        -- last balance the provider reported
  reported_balance_at DATETIME(6) NULL,
  UNIQUE KEY uq_gl_account (gl_account_id),
  FOREIGN KEY (connection_id) REFERENCES bank_connection(id),
  FOREIGN KEY (gl_account_id) REFERENCES account(id)
);

CREATE TABLE bank_txn (                       -- the staging row; the review queue
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  bank_account_id INT NOT NULL,
  source          ENUM('PLAID','SIMPLEFIN','FILE') NOT NULL,
  external_id     VARCHAR(100) NOT NULL,      -- provider id, or a hash for file rows (§5.5)
  posted_date     DATE NOT NULL,
  amount          DECIMAL(14,2) NOT NULL,     -- GL sign: + increases the GL account's debit balance
  description     VARCHAR(255) NOT NULL,      -- raw bank text, never edited
  merchant_name   VARCHAR(120) NULL,          -- provider's cleaned name, if any
  provider_category VARCHAR(120) NULL,        -- a hint only
  status          ENUM('NEW','SUGGESTED','POSTED','EXCLUDED','REMOVED') NOT NULL DEFAULT 'NEW',
  suggested_account_id INT NULL,
  suggested_payee_id INT NULL,
  suggested_rule_id INT NULL,
  suggested_invoice_id INT NULL,              -- Zelle receipt matched to an invoice (§8.4)
  suggested_transfer_txn_id BIGINT NULL,      -- the other side of a transfer (§6.3)
  entry_id        BIGINT NULL,                -- set when POSTED
  excluded_reason VARCHAR(120) NULL,
  raw_json        JSON NOT NULL,              -- as received; record first, interpret later
  first_seen_at   DATETIME(6) NOT NULL,
  UNIQUE KEY uq_bank_txn (bank_account_id, source, external_id),
  KEY ix_bank_txn_status (status, posted_date),
  FOREIGN KEY (bank_account_id) REFERENCES bank_account(id),
  FOREIGN KEY (entry_id) REFERENCES journal_entry(id)
);

CREATE TABLE payee_rule (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  priority        INT NOT NULL DEFAULT 100,   -- lower wins
  match_field     ENUM('DESCRIPTION','MERCHANT') NOT NULL DEFAULT 'DESCRIPTION',
  match_type      ENUM('CONTAINS','STARTS_WITH','EQUALS','REGEX') NOT NULL DEFAULT 'CONTAINS',
  pattern         VARCHAR(200) NOT NULL,
  bank_account_id INT NULL,                   -- NULL = any account
  amount_min      DECIMAL(14,2) NULL,
  amount_max      DECIMAL(14,2) NULL,
  payee_id        INT NULL,
  account_id      INT NULL,                   -- NULL with action EXCLUDE
  action          ENUM('SUGGEST','EXCLUDE','TRANSFER') NOT NULL DEFAULT 'SUGGEST',
  memo_template   VARCHAR(255) NULL,
  times_applied   INT NOT NULL DEFAULT 0,
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,
  FOREIGN KEY (payee_id) REFERENCES payee(id),
  FOREIGN KEY (account_id) REFERENCES account(id)
);

CREATE TABLE invoice (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  number          VARCHAR(20) NOT NULL,       -- 'INV-2027-0001'
  customer_id     INT NOT NULL,
  issue_date      DATE NOT NULL,
  due_date        DATE NOT NULL,
  status          ENUM('DRAFT','OPEN','PAID','VOID') NOT NULL DEFAULT 'DRAFT',
  total           DECIMAL(14,2) NOT NULL DEFAULT 0,
  amount_paid     DECIMAL(14,2) NOT NULL DEFAULT 0,   -- maintained by utils/invoices.py only
  memo            TEXT NULL,                  -- printed on the invoice
  entry_id        BIGINT NULL,                -- the Dr A/R / Cr Income entry, set on issue
  pdf_path        VARCHAR(255) NULL,          -- under /data/invoices
  email_requested_at DATETIME(6) NULL,
  emailed_at      DATETIME(6) NULL,
  UNIQUE KEY uq_invoice_number (number),
  FOREIGN KEY (customer_id) REFERENCES payee(id),
  FOREIGN KEY (entry_id) REFERENCES journal_entry(id)
);

CREATE TABLE invoice_line (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  invoice_id      INT NOT NULL,
  line_no         SMALLINT NOT NULL,
  description     VARCHAR(255) NOT NULL,
  quantity        DECIMAL(10,2) NOT NULL DEFAULT 1,
  rate            DECIMAL(14,2) NOT NULL,
  amount          DECIMAL(14,2) NOT NULL,     -- quantity x rate, rounded half-up, computed server-side
  income_account_id INT NOT NULL,
  UNIQUE KEY uq_invoice_line (invoice_id, line_no),
  FOREIGN KEY (invoice_id) REFERENCES invoice(id),
  FOREIGN KEY (income_account_id) REFERENCES account(id)
);

CREATE TABLE invoice_payment (                -- links a receipt entry to the invoice(s) it pays
  id              INT AUTO_INCREMENT PRIMARY KEY,
  invoice_id      INT NOT NULL,
  entry_id        BIGINT NOT NULL,
  amount          DECIMAL(14,2) NOT NULL,
  FOREIGN KEY (invoice_id) REFERENCES invoice(id),
  FOREIGN KEY (entry_id) REFERENCES journal_entry(id)
);

CREATE TABLE reconciliation (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  gl_account_id   INT NOT NULL,
  statement_date  DATE NOT NULL,
  statement_balance DECIMAL(14,2) NOT NULL,   -- in the account's normal direction
  status          ENUM('IN_PROGRESS','FINISHED') NOT NULL DEFAULT 'IN_PROGRESS',
  finished_at     DATETIME(6) NULL,
  UNIQUE KEY uq_recon (gl_account_id, statement_date),
  FOREIGN KEY (gl_account_id) REFERENCES account(id)
);

CREATE TABLE attachment (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  entry_id        BIGINT NULL,
  bank_txn_id     BIGINT NULL,                -- attach a receipt before posting
  filename        VARCHAR(255) NOT NULL,
  stored_path     VARCHAR(255) NOT NULL,      -- /data/attachments/yyyy/mm/<sha256>.<ext>
  sha256          CHAR(64) NOT NULL,
  content_type    VARCHAR(100) NOT NULL,
  uploaded_at     DATETIME(6) NOT NULL
);

CREATE TABLE settings (                       -- one row
  id              TINYINT PRIMARY KEY DEFAULT 1,
  company_name    VARCHAR(120) NOT NULL,
  company_address TEXT NULL,
  fiscal_year_start_month TINYINT NOT NULL DEFAULT 1,
  lock_date       DATE NULL,
  ar_account_id   INT NOT NULL,
  retained_earnings_account_id INT NOT NULL,
  undeposited_account_id INT NULL,            -- only if a cheque ever arrives
  invoice_prefix  VARCHAR(10) NOT NULL DEFAULT 'INV',
  next_invoice_seq INT NOT NULL DEFAULT 1,
  zelle_recipient VARCHAR(120) NULL,          -- email or phone printed on invoices
  zelle_display_name VARCHAR(120) NULL,       -- the name the customer will see in their bank app
  form_1099_threshold DECIMAL(14,2) NOT NULL DEFAULT 2000.00,
  owner_password_hash VARCHAR(255) NOT NULL,
  totp_secret_ref VARCHAR(60) NULL
);

CREATE TABLE audit_log (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  at              DATETIME(6) NOT NULL,
  action          VARCHAR(60) NOT NULL,       -- 'entry.reverse', 'lock_date.move', ...
  object_type     VARCHAR(40) NOT NULL,
  object_id       BIGINT NULL,
  detail          JSON NULL
);

CREATE TABLE feed_sync_log (                  -- pruned after 180 days
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  connection_id   INT NOT NULL,
  started_at      DATETIME(6) NOT NULL,
  finished_at     DATETIME(6) NULL,
  added INT NOT NULL DEFAULT 0, modified INT NOT NULL DEFAULT 0, removed INT NOT NULL DEFAULT 0,
  error           VARCHAR(500) NULL
);

CREATE TABLE health_finding (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  found_at        DATETIME(6) NOT NULL,
  check_name      VARCHAR(60) NOT NULL,
  detail          JSON NOT NULL,
  resolved_at     DATETIME(6) NULL
);
```

Fifteen tables. For scale: at a few hundred bank lines a month, `journal_line` grows by
under ten thousand rows a year. Retention is permanent for everything except
`feed_sync_log`; seven years of books is a small database.

---

## 5. Bank feeds

### 5.1 The connector interface

The feed is behind one interface so that the provider is a setting, not a rewrite. This
matters more than usual here, because of the Chase question in §5.3.

```python
class FeedConnector(Protocol):
    def sync(self, conn: BankConnection) -> SyncResult: ...
        # returns added / modified / removed lines, per provider_account_id,
        # already normalised to GL sign (§5.4), plus reported balances and the new cursor

class PlaidConnector: ...       # utils/feeds/plaid_feed.py
class SimpleFinConnector: ...   # utils/feeds/simplefin_feed.py
class FileImport: ...           # utils/feeds/file_import.py  (Chase CSV / QFX upload)
```

Every connector writes the same `bank_txn` rows. The review queue, rules, transfer
matching and reconciliation never know which one a line came from.

### 5.2 Plaid

| Step | Endpoint | Where it runs |
| --- | --- | --- |
| Start linking | `/link/token/create` with `products=["transactions"]`, `redirect_uri` for OAuth | web, on click |
| User signs into Chase | Plaid Link (JS from `cdn.plaid.com`) → Chase OAuth → back to `redirect_uri` | browser |
| Keep the connection | `/item/public_token/exchange` → `access_token`, `item_id` | web, once |
| Map accounts | `/accounts/get` → each account's id, mask, type, balances | web, once; then worker |
| Pull transactions | `/transactions/sync` with the stored cursor, looping while `has_more` | worker |
| Balances | `balances.current` returned with `/accounts/get` (cached, no per-call fee) | worker, after sync |
| Re-consent | Link in **update mode** with the existing `access_token` | web, when status is `LOGIN_REQUIRED` |
| Disconnect | `/item/remove` | web, with confirm |

Details that decide correctness:

- **`/transactions/sync`, not `/transactions/get`.** Sync returns `added`, `modified`
  and `removed` against a cursor, so the app never has to diff date windows. The cursor
  is saved **only after every page of a sync has been written** in one database
  transaction. A crash mid-loop therefore replays from the old cursor, and the unique
  key on `bank_txn` absorbs the repeats. Saving the cursor page by page would lose the
  pages after a crash.
- **Pending transactions are ignored.** Only `pending = false` lines are stored. A
  pending card authorisation changes amount (tips, holds) and id when it posts; storing
  it would put a line in the review queue that later disappears.
- **`modified`** updates a `NEW` or `SUGGESTED` line in place. On a `POSTED` line it
  changes nothing in the journal and writes a `health_finding` ("the bank changed a line
  you already posted: was X, now Y"). The books never change underneath you.
- **`removed`** marks a `NEW`/`SUGGESTED` line `REMOVED`. On a `POSTED` line, same
  finding, no journal change. Deciding whether to reverse the entry is yours.
- **No webhooks.** The server accepts no inbound calls without a reviewed exception
  ([NEW-APP-INTEGRATION.md §1 rule 5](NEW-APP-INTEGRATION.md)), and a daily poll is
  plenty for bookkeeping. `ITEM_LOGIN_REQUIRED` is detected on the next sync, sets
  `bank_connection.status`, and shows a `.banner-error` on every page with a
  **Reconnect** link.
- **Chase consent expires.** Chase makes the user choose 6 months, 1 year or
  "always" when linking. Choose "always"; the app still records
  `consent_expires_at` where Plaid reports it and warns 14 days ahead.
- **One Chase login is one Plaid Item.** If the checking account and the card are under
  the same Chase online login, that is one connection and one Item with two accounts.
  This matters for the Item-based pricing and caps below.
- **OAuth redirect.** Production Plaid requires an HTTPS `redirect_uri` registered in
  the Plaid Dashboard: `https://general-ledger.hruskagroup.com/connections/oauth-return`.
  It is the owner's own browser returning there, so nginx Basic Auth and the app login
  are both already satisfied; no firewall or nginx exception is needed. Plaid's Sandbox
  allows `http://localhost`, which is how development works.
- **Environments.** Dev uses Plaid Sandbox with Sandbox keys; production uses production
  keys. Separate credentials per environment, as
  [CREDENTIALS.md §4 rule 6](CREDENTIALS.md) requires. `PLAID_ENV=sandbox` is the
  default when unset.

### 5.3 Plaid pricing and the Chase question

What I could confirm on 2026-09-28:

- Plaid now offers a free **Trial plan** to US teams created on or after 2026-04-15:
  real production data, no business registration or security questionnaire, capped at
  **10 production Items**. This app needs one or two.
- After Trial, **Pay-as-you-go** has no minimum. Transactions is billed as a
  **monthly subscription per Item** for as long as its `access_token` exists. Plaid does
  not publish the per-Item price; it shows it after you request production access.
- **Probably, but not yet proven: whether Trial reaches Chase.** Plaid's Trial plan
  help article explicitly lists OAuth access to Chase, Bank of America, Wells Fargo,
  Capital One, Amex and others. Plaid's older OAuth guide says Trial can test OAuth only
  against Sandbox institutions until a paid upgrade. The Trial article is newer and
  specific, so it probably governs. Chase is OAuth-only on Plaid.
- **Signup choice:** "Personal use — build something for fun" is the path to the Trial
  plan. It needs no company registration or security questionnaire. "Business" routes
  to the production-approval process that the Trial plan exists to skip.

**Resolve this before writing any Plaid code** (§13, question 1): sign up, create a Trial
team, and try linking Chase in production through the Plaid Quickstart. It costs
nothing and settles the question.

If Chase needs a paid plan, the likely cost is one Item's monthly Transactions fee,
which is still well under a QuickBooks subscription. If Plaid's production approval
turns out to be more work than it is worth for one business, the connector interface
(§5.1) lets either alternative take its place without touching the rest of the app:

| Option | Cost | Chase | Effort |
| --- | --- | --- | --- |
| **Plaid** | Trial free (≤10 Items); then a per-Item monthly fee | via OAuth; Trial coverage unconfirmed | Link UI, OAuth redirect, production approval |
| **SimpleFIN Bridge** | $15/year (or $1.50/month) for up to 25 institutions | listed as supported; confirm on their institution search | Simplest: one "setup token" pasted once, then a plain HTTPS GET returns accounts and transactions as JSON |
| **File import** | $0 | Chase offers per-account activity download as CSV or QFX | Manual: download and upload monthly. Always built, as a fallback and for backfill (§10) |

~~**Recommendation: build Plaid as primary, but build the file importer first.**~~

**Decision (owner, 2026-10-01): file import is the primary feed; an automatic feed is
optional and deferred.** A monthly download of two Chase accounts is a few minutes'
work, and file import is already built. Plaid's costs (production approval, per-Item
fees after Trial, consent renewals, the OAuth redirect, the web-process exception in
§2) buy only the removal of that step, and they would weigh on every user if the app is
ever open-sourced or run as a desktop app (`SQLITE_PLAN.md`), where each user would need
their own Plaid developer account. If automation is wanted later, **SimpleFIN comes
first**: each user holds their own token, with no developer approval and no OAuth
redirect. Plaid stays an optional connector for whoever wants it. `PLAID_PLAN.md` is
kept, on hold, so that work starts from settled decisions if it is ever picked up.

### 5.4 Sign normalisation

Every provider has its own sign convention, and getting this wrong silently inverts
half the books. It is handled in exactly one place, each connector's `normalise()`, and
tested with a fixture per provider per account kind.

`bank_txn.amount` is stored **in GL sign for the bank's own GL account**: positive means
a debit to that account.

| Provider | Account kind | Provider says | GL amount |
| --- | --- | --- | --- |
| Plaid | checking | `+` = money **out** | `−amount` (outflow credits the asset) |
| Plaid | credit card | `+` = a **charge** | `−amount` (a charge credits the liability) |
| Plaid | credit card | `−` = a payment or refund | `−amount` (debits the liability) |
| Chase CSV | checking | `−` = money out | `amount` as-is |
| Chase CSV | credit card | `−` = a charge (the "Sale" type) | `amount` as-is |
| SimpleFIN | any | `−` = money out / charge | `amount` as-is |

Plaid's convention is the same for both kinds (positive means money leaving *you*),
which is why one rule covers both. The Chase CSV rows need confirming against a real
download before the importer ships (§13); the table is what they are documented to be.

### 5.5 File import

- Accepts Chase **CSV** (both the checking and the card layouts) and **QFX/OFX**.
  *Built: CSV only.* Chase's QFX truncates descriptions and its checking `FITID` is just
  date + sequence, so Chase stays on CSV. **OFX/QFX/QBO is planned for other banks**
  (owner, 2026-10-01; one parser, since all three are OFX, 1.x SGML and 2.x XML):
  - description = `NAME` joined with `MEMO`, since `NAME` is capped at 32 characters;
  - `FITID` is trusted only where a bank's ids are known to be stable; otherwise the
    content hash below;
  - the file's `ACCTID` must match the chosen bank account (last 4), or the import is
    refused;
  - the file's `LEDGERBAL` (closing balance and date) is compared with the ledger's
    balance on that date and shown on the preview.
- A preview step (wizard, [STYLING.md §5.11](STYLING.md)) shows parsed rows, the date
  range, the count already present, and the sum, before anything is written.
- `external_id` is the QFX `FITID` when present. For CSV, which has no id, it is
  `sha256(bank_account_id | posted_date | amount | description | n)`, where *n* is the
  occurrence number of that identical tuple within the file. Two genuine $5.00 coffees
  on the same day then stay two rows, and re-importing the same file adds nothing.
- **A file overlapping a Plaid-fed period is refused** for the overlapping dates unless
  explicitly overridden, because the two sources have different ids and would
  double-count.

---

## 6. From bank line to journal entry: the review queue

The review queue is where the time goes each month, so it gets the most UI care (§12).
The goal is that a typical month is: open Banking, check that the suggestions are
right, click **Post all suggested**, and deal with the few that have no suggestion.

### 6.1 States

```
NEW ──(rules/matching)──> SUGGESTED ──(you accept)──> POSTED
 │                           │
 └──────────(you)────────────┴──> EXCLUDED     (with a reason: duplicate, personal, pre-cutover...)
REMOVED   (the provider withdrew a line that was never posted)
```

Only a human moves a line to `POSTED` or `EXCLUDED`. Rules and matching produce
suggestions; they never post. This is deliberate, and it is where this design departs
from QuickBooks' "auto-add" rules: an automatic posting that is wrong is invisible until
the tax return, while a wrong suggestion is caught at a glance.

A later setting could allow auto-posting for a rule that has been accepted unchanged
N times; it is not in the first build.

### 6.2 What posting writes

Accepting a line writes one `journal_entry` (`source = 'BANK'`) with two lines: the bank
account for `bank_txn.amount`, and the chosen account for its negation. **Split** lets
you divide the offset across several accounts (a Costco receipt that is part supplies,
part owner draw), provided the splits total the line.

| Bank line | Offset | Entry |
| --- | --- | --- |
| Card charge, $49.00, "GITHUB" | 6120 SaaS | Dr 6120 49.00 / Cr 2010 Card 49.00 |
| Checking ACH debit, $180.00, "AT&T" | 6200 Telephone | Dr 6200 180.00 / Cr 1010 Checking 180.00 |
| Checking deposit, Zelle from a customer, $1,500.00 | 1200 A/R via invoice match (§8.4) | Dr 1010 1,500.00 / Cr 1200 1,500.00 |
| Card refund, $20.00 | the original expense | Dr 2010 20.00 / Cr 6300 20.00 |
| Personal charge on the business card | 3100 Owner Draws | Dr 3100 / Cr 2010 |

Posting also:

- attaches any receipt uploaded against the `bank_txn` to the new entry;
- creates or updates a payee rule when you tick "Remember for *PAYEE*" (checked by default
  when you change the suggested account), and increments `times_applied` when a
  suggestion is accepted unchanged.

### 6.3 Transfers between your own accounts

Paying the Chase card from Chase checking appears **twice**: an outflow on checking and
a payment on the card. Posting both as ordinary lines would double-count it.

The matcher looks for pairs across the two feeds with **equal and opposite GL amounts**
within **five days**, where at least one description looks like a card payment
(`"Payment to Chase card"`, `"AUTOMATIC PAYMENT - THANK"`, or a `TRANSFER` rule). It
suggests them as a pair. Accepting writes **one** entry, Dr 2010 Card / Cr 1010
Checking, and links **both** `bank_txn` rows to it. If only one side has arrived, the
line waits with the suggestion "waiting for the other side" rather than posting to a
clearing account, because the other side reliably arrives within days.

The same logic handles owner contributions and draws between business and personal
accounts, if a personal account is ever connected.

### 6.4 Rule evaluation

Rules are evaluated in `priority` order and the first match wins. Matching is
case-insensitive on normalised whitespace. When no rule matches, the fallback
suggestion is the account most often used with the same `merchant_name` in the last
twelve months, labelled "based on history" so it is distinguishable from a rule. Plaid's
`provider_category` is shown as a hint and never used on its own: a category like
"GENERAL_MERCHANDISE" does not map to a chart of accounts.

---

## 7. Reconciliation

The feed makes reconciliation cheap but does not replace it. The feed proves every line
arrived; reconciliation proves that nothing arrived twice, nothing is missing, and the
GL agrees with the bank's statement.

1. Setup → Reconcile → pick the account and enter the statement's ending date and
   balance.
2. The page lists every uncleared GL line on that account up to the statement date,
   with lines from the feed pre-ticked (they came from the bank, so they cleared).
3. The page shows **Cleared balance**, **Statement balance** and **Difference**, all
   computed on the server. **Finish** is disabled until the difference is `0.00`.
4. Finishing stamps `journal_line.cleared_recon_id` on the ticked lines. A reconciled
   line's entry can still be reversed, but the UI warns that it will unbalance a
   finished reconciliation and names it.

Between statements, the Dashboard shows each bank account's GL balance beside the
provider-reported balance (`bank_account.reported_balance`), with the difference
explained by unposted queue lines. An unexplained difference is a health finding, never
an adjustment.

---

## 8. Invoicing

### 8.1 Lifecycle

```
DRAFT ──issue──> OPEN ──payments total the invoice──> PAID
  │                │
  └─delete         └─void (writes a reversing entry)──> VOID
```

- **Draft** has no journal entry and can be edited or deleted freely.
- **Issue** assigns the next number (`INV-2027-0001`; the sequence never reuses a
  number, including after a void), renders the PDF to `/data/invoices/`, and posts
  `Dr 1200 A/R / Cr income` for each line's income account. From then on the lines are
  immutable, like any posted entry.
- **Void** posts the reversal and keeps the invoice, with its number, marked VOID.
  A gap in invoice numbers is a question an auditor asks; a VOID invoice answers it.
- `invoice.amount_paid` and `status` are maintained only by `utils/invoices.py` from
  `invoice_payment` rows, and the integrity check (§3.5) confirms that open invoice
  balances agree with the A/R account.

### 8.2 The PDF

Generated by **fpdf2** (pure Python, no system libraries, so the image stays as the
integration doc's Dockerfile describes). One layout: company name and address, invoice
number, dates, bill-to, a lines table, total, memo, and a **How to pay** box:

> **Pay by Zelle** to `billing@yourcompany.com` (shows as *Your Company LLC*).
> Put **INV-2027-0001** in the memo.
> [QR code]

About "Zelle link": Zelle has **no payment-request URL a third party can generate**.
What exists is the recipient's enrolled email or phone and, in most bank apps, a
Zelle QR code for that recipient. The invoice therefore prints the enrolled address and
the display name customers will see in their bank app (so they can confirm they are
paying the right business), plus the invoice number to use as the memo. If you have a
QR code from the Chase app, upload it once in Settings and it prints on every invoice;
the app never generates one itself, since a QR the bank did not issue would be exactly
the thing a careful customer should distrust.

### 8.3 Email

Outbound SMTP (Google Workspace or similar), which the server permits. The SMTP
password is a Reading/Acting-class secret resolved via `utils/credentials.py`
(§11). "Send" writes `invoice.email_requested_at`; the worker sends with the PDF
attached and sets `emailed_at`. The invoice shows *Queued*, then *Sent 10:42*, and a
failure shows on the invoice with the SMTP error, not as a silent retry loop.
Reminders for overdue invoices are the same mechanism, manually triggered in the first
build.

### 8.4 Matching Zelle receipts to invoices

A Zelle deposit arrives on the checking feed looking like
`Zelle payment from JANE DOE 1234567890`. The matcher suggests an open invoice when:

1. the amount equals an open invoice's balance, **and** the sender name matches the
   customer's name or one of its aliases; or
2. the description contains an open invoice number (customers who used the memo); or
3. the amount equals exactly one open invoice's balance and nothing else is a candidate
   (weaker; labelled as such).

Accepting writes `Dr 1010 Checking / Cr 1200 A/R` and an `invoice_payment` row. A
partial payment leaves the invoice OPEN with its balance reduced. A payment covering two
invoices is a split with two `invoice_payment` rows. When the payer's bank name differs
from the customer's (a spouse, a company account), the accept dialog offers "remember
*JANE DOE* as an alias for *Acme LLC*", stored as a `payee_rule` with `payee_id` set.

Cheques are rare but possible: record them against `undeposited_account_id` and let the
deposit line clear it. That is the only use of an undeposited-funds account here.

---

## 9. Reports

All computed on the server in `utils/reports.py` and returned as JSON for the page to
format ([STYLING.md §6.4](STYLING.md)), with a **CSV** download of the same rows for the
accountant. Every report takes a date range; each lists every account with activity,
sorted by account number, with header accounts rolling up their children.

| Report | Shows |
| --- | --- |
| Profit & Loss | income and expense by account for a range; **comparison column** (prior period or prior year); accrual or cash basis (§9.2) |
| Balance Sheet | assets, liabilities, equity at a date, with retained earnings and current-year net income computed (§3.4); balance check shown |
| Trial Balance | every account's debit or credit balance at a date; totals must be equal, and the report says so |
| General Ledger detail | every line by account for a range, with opening and closing balances and links to entries |
| Account register | one account's lines with a running balance, cleared flag and bank description; the page a bank account opens to |
| A/R aging | open invoices by customer in Current / 1–30 / 31–60 / 61–90 / 90+ |
| Tax summary | income and expense grouped by `tax_line`, for handing to the preparer |
| 1099 vendors | calendar-year payments to `is_1099_vendor` payees, **excluding card payments**, which the card processor reports on 1099-K instead. Flags any at or over `settings.form_1099_threshold`, whose default is $2,000: the threshold for payments made from 2026 onward, up from $600. It is a setting because it is now indexed to inflation. |
| Journal | entries by date with all lines, for audit |

### 9.1 Drill-down

Every figure in P&L, balance sheet and trial balance is a link to the general ledger
detail filtered to that account and range, and every GL line links to its entry, the
entry to its bank line, and the bank line to its raw provider row. From any number on
the tax summary you can reach the bank text it came from in three clicks.

### 9.2 Cash-basis P&L

Revenue on a cash basis is the payments, not the invoices. The report recognises income
on the date of each `invoice_payment`, allocated across the invoice's income accounts in
proportion to its lines. Expenses are already cash-basis. No second set of books; the
same journal, read differently.

---

## 10. Migrating from QuickBooks Online

**Export everything from QuickBooks before cancelling.** Keep the export files
permanently; they are the only record of history before the cutover.

### 10.1 Cut over at a year boundary

Recommended cutover: **January 1, 2027**. Then the 2026 tax year is prepared entirely
from QuickBooks, and the new ledger starts on a clean fiscal year with no prior-year
income to reconstruct.

| From QuickBooks | Into the new ledger |
| --- | --- |
| Chart of accounts (Settings → Chart of accounts → export) | `account`, numbered and mapped to `tax_line` by hand in a one-time import wizard |
| Customer and vendor lists (export) | `payee` |
| **Trial balance at 12/31/2026** | one `OPENING` journal entry dated 2026-12-31: every balance-sheet account at its balance; income and expense rolled into retained earnings |
| Open invoices at 12/31/2026 (A/R aging detail) | imported as OPEN invoices with `entry_id` pointing at the opening entry, so A/R agrees without double-posting |
| Uncleared bank and card items at 12/31/2026 | included in the opening entry's bank balances as uncleared, so the first reconciliation starts from the right place |
| General ledger detail, all years | kept as exported files; optionally imported as `IMPORT` entries for lookup (not needed for any report after cutover) |

Set `bank_account.feed_start_date = 2027-01-01` and the lock date to 2026-12-31 as the
last step. Anything the feed returns from before the cutover is then ignored rather than
queued (Plaid returns up to 24 months of history on first sync, and none of it should
be posted twice).

### 10.2 Run in parallel for one month

Keep QuickBooks for January 2027 and book the month in both. The P&L and balance sheet
for January should agree to the cent. Where they differ, the difference is either a
bug here or a categorisation choice, and a month is enough to find out which. Then
cancel.

---

## 11. Security and credentials

| Credential | Class ([CREDENTIALS.md §1](CREDENTIALS.md)) | Where, in production |
| --- | --- | --- |
| Plaid `client_id` / `secret` | Acting (can create Items and read data) | tier 2 encrypted file, `/etc/general-ledger/plaid.enc` |
| Plaid `access_token` per Item | Reading (read-only transactions, but the full history of the business's money) | tier 2, `<credential_ref>.enc`; `bank_connection.credential_ref` holds only its name |
| SimpleFIN access URL, if used | Reading (it embeds a credential) | tier 2 |
| SMTP password | Acting (sends mail as you) | tier 2 |
| Keystore passphrase | — | `env/general-ledger.env` in the infra repo, a different tree from the ciphertext |
| Owner password | — | Argon2 hash in `settings.owner_password_hash` |
| Customer/vendor TINs (for 1099s) | Identifying, but tax-sensitive | tier 2 by `payee.tax_id_ref`, or simply not stored (the preparer has the W-9s) |

Copy `utils/credentials.py` and `utils/keystore.py` from `trade-portfolio` rather than
writing them again, as [CREDENTIALS.md §6](CREDENTIALS.md) says.

**App login.** This app can move nothing (it cannot pay, transfer or initiate
anything; Plaid Transactions is read-only), but it can read the full financial history of
the business, and the nginx Basic Auth password is shared across every site. So per
[NEW-APP-INTEGRATION.md §6](NEW-APP-INTEGRATION.md) it gets its own login:

- one owner account; password as an Argon2 hash; optional TOTP as a second factor;
- Flask session cookie `HttpOnly`, `SameSite=Strict`, `Secure` when `APP_HTTPS=1`,
  expiring after 12 hours idle;
- every state-changing route requires a JSON content type (the `api()` helper always
  sends one), which a cross-site form cannot forge;
- `/healthz` is exempt, as the container contract requires; everything else redirects
  to `/login`.

None of the sibling apps has an app-level login yet. This one is small enough
(`routes/auth_routes.py` plus a `before_request` hook) to serve as the pattern for the
next.

**Receipts and invoices on disk** are under `/data`, which is backed up nightly. That
is intended: they are business records. The secrets directory is excluded from the
backup, per the credentials doc.

---

## 12. UI

Built strictly to [STYLING.md](STYLING.md): `base.html`, one stylesheet, `api()`,
server-computed figures, no fallbacks.

### 12.1 Top navigation

Proposed, **for your approval** (STYLING.md §4 reserves the top nav to the owner):

| Nav item | Page | Sub-menu |
| --- | --- | --- |
| Dashboard | `/` | — |
| Banking | `/banking` | Review · Reconcile · Connections · Import file |
| Journal | `/journal` | Entries · New entry · Registers |
| Invoices | `/invoices` | Invoices · Customers |
| Reports | `/reports` | P&L · Balance Sheet · Trial Balance · GL Detail · A/R Aging · Tax · 1099 |
| Setup | `/setup` | Accounts · Payees · Rules · Settings · Health |

### 12.2 Dashboard

- **Hero panel**: cash (checking balance), with metrics for card balance, A/R open,
  and net income year to date.
- **Stat tiles**: lines awaiting review, open invoices, overdue invoices, health findings.
- A section per bank account: GL balance, provider-reported balance, difference,
  last synced, **Sync now** (`setBusy`, status line reports "Added 12, modified 1").
- A `.banner-error` at the top of every page while any connection is `LOGIN_REQUIRED`,
  linking to Reconnect.

### 12.3 Banking → Review (the page used most)

A `.table-scroll` of queue lines, newest first, with a `.segmented` filter
(All · Suggested · No suggestion · Transfers · Excluded):

| Date | Account | Description | Amount | Suggested payee | Suggested account | Why | |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 01/14 | Ink ··1234 | GITHUB INC | −$49.00 | GitHub | 6120 SaaS | `rule` chip | Post · Split · Exclude |
| 01/15 | Chk ··5678 | Zelle payment from JANE DOE | +$1,500.00 | Acme LLC | INV-2027-0003 | `invoice` chip | Post |

- The account cell is an editable select; changing it marks the row `.has-changes` and
  offers "Remember" (§6.2).
- Row checkboxes and **Post selected** / **Post all suggested** with a count in the
  button label ("Post 23 suggested"). The response reports partial success as partial:
  "Posted 21, 2 refused (dated before lock date)".
- A receipt can be dragged onto a row to attach it before posting.
- Keyboard: `j`/`k` to move, `Enter` to post the selected row, `e` to exclude, `s` to
  split. At a few hundred lines a month this is what makes the monthly session minutes
  rather than an hour.

### 12.4 Other pages

- **Journal → New entry**: a lines grid with Debit and Credit columns, a live
  "Out of balance by $X" line computed by the server on each change (`POST
  /api/journal/validate`), and Save disabled until it reads balanced.
- **Registers**: account register (§9) with a running balance.
- **Invoices**: list with status chips (DRAFT neutral, OPEN info, PAID success, VOID
  neutral, overdue warning); the editor is one section with lines and a live total;
  **Issue** and **Send** are separate buttons with a confirm on Issue, because Issue
  posts to the books.
- **Reconcile**: §7, with the difference as the one hero figure.
- **Connections**: each connection's status dot, accounts, last sync, consent expiry,
  and Connect / Reconnect / Disconnect.

---

## 13. Build order

Each phase is usable on its own, and nothing depends on the Plaid decision until
phase 4.

| Phase | Delivers | Can you stop here? |
| --- | --- | --- |
| **0. Skeleton** | Repo per the integration doc: Dockerfile, `compose.dev.yml`, Alembic, `base.html`, login, `/healthz`, synced `docs/`, `CLAUDE.md` | — |
| **1. Core ledger** | Chart of accounts, `post_entry()` with every §3.1 rule and its tests, reversal, lock date, manual journal entry, account register, trial balance | A working manual ledger |
| **2. File import + review queue** | Chase CSV/QFX import, `bank_txn`, review queue, rules, transfers, splits, attachments | Already replaces QBO's bank feed, with a monthly download |
| **3. Reports + migration** | P&L, balance sheet, GL detail, tax summary, CSV export, QuickBooks opening-balance import | **QBO can be cancelled here** |
| **4. Automatic feed** (optional, deferred 2026-10-01; SimpleFIN first, Plaid optional) | Connector, sync worker, balances, reconnect | Removes the monthly download |
| **5. Invoicing** | Invoices, PDF, SMTP, Zelle matching, A/R aging | Full replacement |
| **6. Polish** | Reconciliation page, 1099 report, cash-basis P&L, integrity check, keyboard shortcuts | — |

Invoicing is phase 5 rather than 2 only because a few invoices a month can be kept in
QuickBooks' last month, or issued by hand and posted as manual entries, until then. If
invoices are more frequent than that, swap phases 4 and 5.

---

## 14. Open questions

1. **Does Plaid's Trial plan link Chase in production?** Settles §5.3. Test with the
   Plaid Quickstart before phase 4. If not: how much is one Transactions Item per month
   on Pay-as-you-go, and is production approval worth it versus SimpleFIN's $15/year?
2. **Are the Chase checking account and the Ink card under one Chase login?** One Item
   or two (§5.2).
3. **The QuickBooks plan being cancelled, and its annual cost** — the number this is
   measured against. Hosting here is marginal: the Photon server, MySQL and nightly
   backups already exist.
4. **Entity type** (sole proprietor / single-member LLC → Schedule C; S-corp → 1120-S),
   which decides the `tax_line` list the seed chart uses.
5. **A real Chase CSV from each account**, to confirm the column layouts and signs in
   §5.4 before the importer ships.
6. **Cutover date**: 2027-01-01 as recommended, or earlier with a mid-year opening
   balance?
7. **Top nav** (§12.1): approve the six items, or trim.
8. **SMTP provider** for invoice email, and the from-address.

<!-- EOF - DESIGN.md -->
