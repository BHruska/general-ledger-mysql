# General Ledger — Backlog

Things decided to do later, so they are not lost between sessions. This file belongs to
this project (it is not a synced copy from `_standards`). The build order itself lives in
[DESIGN.md §13](DESIGN.md); this is what sits outside it or was deferred from it.

## Deferred by the owner

| Item | From | Notes |
| --- | --- | --- |
| Keyboard shortcuts on Banking → Review | DESIGN.md §12.3 | `j`/`k` to move, `Enter` post, `e` exclude, `s` split. Deferred 2026-09-30. |

## Ideas to investigate

| Item | Notes |
| --- | --- |
| Check images for paper checks | "CHECK 1028" names no payee, so the owner looks it up on chase.com. As far as known, Plaid's Transactions product returns no check images; confirm with Plaid's docs, else options are a manual upload (the receipts button already takes images) or Chase's own export. Owner's idea, 2026-09-30. |
| Choose a payee when posting | Checks and anonymous deposits could then carry a payee (and update its last-used date) even though their text never will. |

## Worth doing

| Item | Why |
| --- | --- |
| TOTP second factor for the owner login | DESIGN.md §11 marks it optional; deferred in phase 0. Plaid's questionnaire may ask about MFA if the plan is ever upgraded from Trial. |
| Payee phone, company and account number | The QBO vendor list carries them; the `payee` table has only email and address. |
| QFX import | Deliberately left out (CSV carries full descriptions). Revisit only if a bank offers no CSV. |

## Open questions

See [DESIGN.md §14](DESIGN.md) and [PLAID_PLAN.md](../PLAID_PLAN.md) (Open questions).

<!-- EOF - BACKLOG.md -->
