# SQLite + Desktop App Plan

**Draft — 2026-10-01. Not approved; nothing here is built.**

Replace MySQL with SQLite and run the ledger as a Windows desktop app (pywebview over a
local waitress server), with no Docker. This takes the project off the Photon contract
in `docs/NEW-APP-INTEGRATION.md`; if adopted, record that departure in `DESIGN.md` and
`CLAUDE.md` (the integration doc is a synced standard and stays as it is).

## 0. Decisions before starting

1. **Replace MySQL, don't support both.** Two backends means two test runs and two sets
   of quirks, for one user.
2. **Moving the existing data:** a one-time copy script from MySQL to SQLite, verified by
   an identical trial balance. A `rebuild-from-qbo` would lose any lines posted after the
   boundary.
3. **No bank-feed dependency (settled 2026-10-01).** File import is the primary feed and
   an automatic feed is optional and deferred, with SimpleFIN ahead of Plaid
   (`docs/DESIGN.md` §5.3). That removes Plaid's desktop OAuth question from this plan
   (phase 7).
4. **Stay cross-platform.** Windows is the only target, but nothing should rule out a
   Mac or Linux build if the app is open-sourced: `platformdirs` for the data folder,
   `portalocker` for the instance lock, `keyring` for credentials, and no Windows-only
   APIs. CI can run the SQLite suite on Windows and macOS runners.

## Target shape

```
GeneralLedger.exe  (PyInstaller, one folder)
 ├─ instance lock    %LOCALAPPDATA%\GeneralLedger\ledger.lock
 ├─ migrations       alembic upgrade head, before anything else starts
 ├─ web thread       waitress on 127.0.0.1:8001
 ├─ worker thread    today's tick() loop, same shutdown Event
 └─ pywebview        WebView2 window pointed at the local server

%LOCALAPPDATA%\GeneralLedger\
   ledger.db (+ -wal, -shm)   attachments\   invoices\   backups\   logs\
```

The data folder comes from `platformdirs` (`%LOCALAPPDATA%\GeneralLedger` on Windows,
`~/Library/Application Support/GeneralLedger` on a Mac). Credentials (`session_secret`,
any feed token) move to the OS keyring tier: Windows Credential Manager or the macOS
Keychain, both already supported by `utils/credentials.py` through `keyring`. The data folder must
**not** be inside OneDrive: a sync client running against a live SQLite file corrupts
it. Backup copies can go to OneDrive.

---

## Phase 1: Money as integer cents (do this first; test-covered)

SQLite has no decimal type. SQLAlchemy's `Numeric` stores floats there, and `SUM()`
becomes float math, which breaks the money rule.

- Add a `Money` `TypeDecorator` in `utils/money.py`: `BigInteger` underneath, `Decimal`
  at the edges. Writing a value with more than 2 decimal places **raises an error**
  rather than rounding. Add a `Hundredths` type for `invoice_line.quantity`.
- Swap all 11 `Numeric` columns in `models.py`.
- **Check SQL arithmetic and aggregates.** `func.sum(JournalLine.amount)` should keep the
  `Money` type, but `Invoice.total - Invoice.amount_paid` may come back as a bare integer
  of cents. Each call site needs a test that asserts it gets a `Decimal`; wrap with
  `type_coerce(..., Money)` where it doesn't. The call sites are
  `utils/bank_accounts.py` (account sums), `utils/invoices.py` (open total, customer
  stats, payments), `utils/journal.py` (trial balance), `utils/reports.py` and
  `utils/statements.py` (account sums).
- Replace `func.if_` in `utils/invoices.py` `list_customers()` with `case()`. `IF()` is
  MySQL-only.

**Exactness guarantees.** Integer cents involve no rounding at all: SQLite stores and
adds 64-bit integers exactly, and `SUM()` over integers returns an integer (raising on
overflow, about 92 quadrillion dollars, rather than going to float). Floats can only
enter at the places below, and each one fails loudly instead of rounding:

| Where | Safeguard |
| --- | --- |
| A REAL stored in a money column | **STRICT tables** (SQLite 3.37+): an INTEGER column refuses `49.5` with an error. |
| Decimal → cents on write | Exact `Decimal` arithmetic; more than 2 places is refused, never rounded (MySQL `DECIMAL(14,2)` silently rounds today, so this is stricter). |
| A float coming back from the database | `Money.process_result_value` raises on anything but `int` (or `None`). |
| SQL that makes fractions: `/`, `AVG()`, `TOTAL()`, REAL literals | A test scans the code and fails on those applied to money columns; never use them. |
| Arithmetic losing the `Money` type | A test per aggregate asserting a `Decimal` comes back (above). |

The only intentional rounding stays in Python `Decimal` with an explicit `ROUND_HALF_UP`
before storage, untouched by this change: invoice quantity × rate
(`utils/invoices.py`) and the derived rate on QuickBooks invoice import
(`utils/migration/qbo_invoices.py`).

**Done when:** the suite passes, still on MySQL, with cents storage. Landing this on
MySQL first separates the money change from the engine change.

## Phase 2: Engine and connection layer

In `db.py`:
- Default URL `sqlite:///<data dir>/ledger.db`.
- Remove the `time_zone` connect hook and the MySQL `DATETIME(fsp=6)`; `utc_timestamp()`
  becomes a generic `DateTime`. SQLite keeps microseconds as ISO text.
- On every connect, set:
  - `foreign_keys=ON`: **SQLite ignores foreign keys by default.**
  - `journal_mode=WAL`, so readers don't block the writer.
  - `busy_timeout=5000`.
  - `synchronous=FULL`, because this is a ledger.
- Use the SQLAlchemy pysqlite recipe: driver-level autocommit off, and `BEGIN IMMEDIATE`
  on every transaction. The write lock is then taken at the start, so the
  `with_for_update()` calls are harmless and invoice numbering stays serialized. Leave
  those calls in place as documentation of intent.
- Drop `pool_pre_ping` and `pool_recycle`, and drop PyMySQL and gunicorn from
  requirements. Add waitress, pywebview and portalocker.

**Collation:** MySQL's default collation is case- and accent-insensitive; SQLite
compares exactly. Add `COLLATE NOCASE` to `payee.name` (unique, and looked up by name in
`utils/bank_queue.py`, `utils/invoices.py` and `utils/payees.py`) and to customer names.
Add a test that "ACME" and "Acme" are treated as the same payee. NOCASE only folds
ASCII, which is fine for these names.

## Phase 3: Schema, triggers, migrations

- **Squash 0001–0008** into one SQLite baseline (`0001_sqlite_baseline`). The MySQL
  history doesn't apply to the new file. In `alembic/env.py`, set
  `render_as_batch=True` for future migrations, because SQLite's `ALTER TABLE` is
  limited.
- **Port the five triggers** from `alembic/versions/0002_core_ledger.py`: `SIGNAL`
  becomes `SELECT RAISE(ABORT, '...')`, `<=>` becomes `IS`, and `IF` becomes the
  trigger's `WHEN` clause. They raise `sqlite3.IntegrityError` with the same messages.
  The `log_bin_trust_function_creators` infra request goes away.
- **SQLite has no `TRUNCATE`, so `DELETE` always fires the triggers.** That changes two
  things:
  - `reset_dev_database()` in `utils/migration/rebuild.py` is replaced by **rebuilding
    into a new file and swapping it in**: build `ledger.rebuild.db`, verify it, then
    rename the old file to `ledger.<timestamp>.db` and the new one into place. That's
    safer than today's reset, and the old book survives.
  - Tests: see phase 4.
- Replace `GET_LOCK` in `alembic/env.py` with the instance lock from phase 5. Migrations
  run only in the process that holds it.

## Phase 4: Tests

- In `conftest.py`, migrate one **template** `.db` per session, then copy that file into
  a temp path for each test. A file copy of a small database takes about a millisecond
  and avoids the trigger problem entirely. The `*_test` safety check becomes "must be
  under the temp directory".
- Remove the `SET FOREIGN_KEY_CHECKS` and `TRUNCATE` code.
- New tests:
  - the triggers block update/delete and posting on the lock date;
  - NOCASE payee uniqueness;
  - `Decimal` comes back from every aggregate;
  - over-precision amounts are refused;
  - concurrent writes, which wait and never fail with "database is locked".
- Update `CLAUDE.md`: tests need no Docker.

## Phase 5: One process: launcher, worker thread, lock

Add a new `desktop.py`, the entry point:
1. Take an exclusive `portalocker` lock on `ledger.lock`. If another instance holds it,
   open the existing window's URL and exit. This replaces `SingleWriterLock` and the
   migration lock.
2. Run `alembic upgrade head` in-process.
3. Start waitress on `127.0.0.1:8001` in a daemon thread. A fixed port keeps bookmarks
   and any future feed redirect stable.
4. Start the worker loop in a thread. `worker.py` already has `_shutdown` as an Event;
   refactor `main()` into `run(shutdown_event)` and drop the signal handlers in this
   mode.
5. `webview.create_window("Ledger", "http://127.0.0.1:8001/")` and `webview.start()`.
6. When the window closes: set the shutdown event, let the worker finish its current
   job, run a WAL checkpoint, take a backup (phase 6), release the lock.

Also:
- `DATA_DIR` and `SECRETS_DIR` in `config.py` default to the `platformdirs` user data
  folder.
- Logs go to rotating files under `logs\`, since there's no console.
- **First run:** generate `session_secret` straight into the keyring.

**Login:** keep the password login unchanged for now; it still guards the loopback port
against other local processes. A later convenience is a one-time launch token the
launcher passes to the window, so it signs in automatically. Setting the password moves
from `manage.py set-password` to the first-run screen *only with the owner's approval*;
`CLAUDE.md` currently forbids setting it through a web form.

## Phase 6: Backups

- Use the online backup API (`sqlite3.Connection.backup`), which is safe while the app is
  running. It runs on window close, plus daily from the worker, to
  `backups\ledger-YYYY-MM-DD.db`. Keep 14 daily and 12 monthly copies.
- Attachments and invoice PDFs are written once and never change, so the backup copies
  only new files.
- Settings gets a **backup folder** setting (e.g. a OneDrive folder) and a "Back up now"
  button. The status panel shows the last backup time, and the backup is checked with
  `PRAGMA integrity_check`.
- Restore is a written procedure: close the app and swap the file. It is not a web
  feature.

## Phase 7: Automatic feed on a local app (deferred)

**Deferred 2026-10-01**, with the feed itself (`docs/DESIGN.md` §5.3); nothing in phases
1–6 or 8–11 depends on it. If it is picked up:
- A scheduled sync only happens while the app is open: sync at launch if the last sync
  is more than 20 hours old, plus on schedule while open, plus "Sync now".
- **SimpleFIN** fits a desktop app well: a pasted token and plain HTTPS GETs, no browser
  flow.
- **Plaid** would reopen the Chase OAuth question: Link inside WebView/WKWebView, and
  `PLAID_PLAN.md` registers `http://localhost` for sandbox only. Check with the Plaid
  MCP (`build_guidance`) before any code; Hosted Link opened in the system browser is
  the likely answer.

## Phase 8: Data cutover

- `manage.py copy-from-mysql <url> <sqlite path>` copies table by table in dependency
  order and keeps ids. It loads first, then creates the triggers.
- **It refuses to finish unless the copy matches the source:**
  - row counts match per table;
  - the trial balance is identical on both sides;
  - every entry sums to 0.00;
  - every attachment hash exists on disk.
- Copy `/data` (attachments and invoices) from the Docker volume into the new data
  folder.

## Phase 9: pywebview polish

- **Downloads** (invoice PDFs, exports): turn on `ALLOW_DOWNLOADS`, or route them through
  a small `js_api` that saves the file or opens it in the default viewer.
- **Uploads** (Chase CSV, receipts): `<input type=file>` already works in WebView2. Check
  drag-and-drop.
- `alert`/`confirm` work. Links to outside sites open in the system browser.
- Remember the window size and position. Turn off the right-click "Inspect" menu in
  builds.

## Phase 10: Packaging

- **PyInstaller, one-folder mode.** It starts faster and triggers fewer antivirus false
  positives than one-file. Bundle `templates/`, `static/`, `alembic/` and the version.
  Windows 11 already includes the WebView2 runtime.
- PyInstaller cannot cross-build: a Mac `.app` is built on a Mac (or a CI macOS runner)
  and, unsigned, needs right-click → Open the first time; Apple notarization costs
  $99/year. Not a goal now (decision 4 only keeps the door open).
- Add a Start Menu shortcut. An Inno Setup installer can come later.
- The CLI commands stay available as `GeneralLedger.exe manage <command>`, e.g. imports
  and rebuild.
- Without code signing, SmartScreen warns on first run. That's acceptable for personal
  use.

## Phase 11: Cleanup and docs

- Delete `Dockerfile`, the `compose.dev.yml` files, `docker/`, `wsgi.py` and the MySQL
  bits of `scripts/dev_init.py`.
- Rewrite the `CLAUDE.md` sections on local development, build order and names.
- In `DESIGN.md`, record the decision and its date.
- Strike the `log_bin_trust_function_creators` note.
- Re-point the `/data` backup claims in `DESIGN.md` at phase 6.

---

## Order and size (rough)

| Phase | Size | Risk |
|---|---|---|
| 1 Money as cents | 1 day | **High value:** catches float leaks |
| 2–4 Engine, schema, tests | 1.5–2 days | Collation and the trigger reset |
| 5 Launcher and threads | 1 day | Low |
| 6 Backups | 0.5 day | Low |
| 8 Cutover | 0.5 day | Verified by trial balance |
| 9–10 Polish and packaging | 1 day | PyInstaller hidden imports |
| 7 Automatic feed | deferred | Not needed for the desktop app |

The app is usable as a desktop app after phases 1–6 plus 8. Packaging is optional until
a double-click `.exe` is wanted.

## Alternative considered: keep MySQL, run it natively

MySQL 8.0 installed as a Windows service (or a Homebrew service on a Mac), with the app
run by waitress plus a worker thread and opened in pywebview or a browser. The code is
almost unchanged: only the launcher, waitress in place of gunicorn, and config defaults.
The cost is a database server to install, patch and back up (`mysqldump`) on each
machine, and the app cannot ship as one self-contained file.
