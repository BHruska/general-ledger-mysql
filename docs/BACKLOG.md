# General Ledger — Backlog

Things decided to do later, so they are not lost between sessions. This file belongs to
this project (it is not a synced copy from `_standards`). The build order itself lives in
[DESIGN.md §13](DESIGN.md); this is what sits outside it or was deferred from it.

## Deferred by the owner

| Item | From | Notes |
| --- | --- | --- |
| Keyboard shortcuts on Banking → Review | DESIGN.md §12.3 | `j`/`k` to move, `Enter` post, `e` exclude, `s` split. Deferred 2026-09-30. |
| Tax summary (Schedule C) | DESIGN.md §9, phase 3 | Entity is a single-member LLC, so Schedule C lines. Needs a tax line on every income and expense account (propose a mapping from names and QBO detail types for the owner to review), then the report grouping by it. Deferred 2026-09-30. |
| Automatic bank feed | DESIGN.md §5.3, §13 phase 4 | File import is primary. If automation is wanted: SimpleFIN first (user-held token, no approval, no OAuth redirect), Plaid only as an optional connector. `PLAID_PLAN.md` is on hold. Deferred 2026-10-01. |
| Invoice email (SMTP) | DESIGN.md §8.3 | Waits on the owner choosing an SMTP account and from-address (§14 Q8). Download the PDF meanwhile. |

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
| OFX/QFX/QBO import | For banks other than Chase, which stays on CSV (its QFX truncates descriptions). The nearest thing to a common bank format, so it matters for open source. Adds an account-number check and a closing-balance check that CSV cannot give. Spec in DESIGN.md §5.5. Decided 2026-10-01. |

## Open questions

See [DESIGN.md §14](DESIGN.md) and [PLAID_PLAN.md](PLAID_PLAN.md) (Open questions).

<!-- EOF - BACKLOG.md -->
