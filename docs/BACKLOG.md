# General Ledger — Backlog

Things decided to do later, so they are not lost between sessions. This file belongs to
this project (it is not a synced copy from `_standards`). The build order itself lives in
[DESIGN.md §13](DESIGN.md); this is what sits outside it or was deferred from it.

## Deferred by the owner

| Item | From | Notes |
| --- | --- | --- |
| Keyboard shortcuts on Banking → Review | DESIGN.md §12.3 | `j`/`k` to move, `Enter` post, `e` exclude, `s` split. Deferred 2026-09-30. |

## Worth doing

| Item | Why |
| --- | --- |
| TOTP second factor for the owner login | DESIGN.md §11 marks it optional; deferred in phase 0. Plaid's questionnaire may ask about MFA if the plan is ever upgraded from Trial. |
| Payee phone, company and account number | The QBO vendor list carries them; the `payee` table has only email and address. |
| QFX import | Deliberately left out (CSV carries full descriptions). Revisit only if a bank offers no CSV. |

## Open questions

See [DESIGN.md §14](DESIGN.md) and [PLAID_PLAN.md](../PLAID_PLAN.md) (Open questions).

<!-- EOF - BACKLOG.md -->
