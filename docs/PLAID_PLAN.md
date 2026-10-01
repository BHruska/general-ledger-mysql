# Plaid Plan

**On hold (owner, 2026-10-01).** File import is the primary feed; an automatic feed is
optional and deferred, with SimpleFIN ahead of Plaid. See DESIGN.md §5.3. This plan
is kept so the work starts from settled decisions if it is ever picked up.

## Goal

Import bank transactions into our general ledger (workflow_id: wf_a0ca28df5fdf34b1).
Chase checking and the Chase Ink card feed the review queue described in
[DESIGN.md §5–6](DESIGN.md). Plaid work is **phase 4** of the design's build
order (§13). This plan is written ahead of time so phase 4 starts from settled decisions.

## Scope

- Products: **transactions** only, in Link `products`; nothing in
  `required_if_supported_products`, `optional_products` or `additional_consented_products`.
  - transactions: ongoing posted lines from Chase checking and the Chase card via
    `/transactions/sync`; daily balances come free with `/accounts/get` and cover the
    reconciliation and integrity checks in DESIGN §3.5 and §7 (SELECT-001, SELECT-015, CONV-001).
- Rejected alternatives:
  - auth: no money moves, and auth alongside transactions silently drops credit-card
    accounts from Link, which would lose the Ink card (TXN-021, SELECT-008).
  - balance (`/accounts/balance/get`): billed per call; nothing here needs a real-time
    funds check (SELECT-005, BAL-001).
  - recurring_transactions add-on: the app has payee rules; no subscription detection needed (TXN-016).
  - identity / identity_match: the owner links their own business accounts; verification
    needs are undecided and not required now (SELECT-004, SELECT-010).
  - additional_consented_products (e.g. auth for future money movement): left out so the
    access token stays read-only transactions, per DESIGN §11. Adding a product later means
    one Link update-mode re-consent (CONV-011, TXN-020), an acceptable cost for one Item.
  - SimpleFIN / file import: SimpleFIN stays the fallback behind the `FeedConnector`
    interface (DESIGN §5.1); file import is built first regardless (DESIGN §5.3).
- Platform: Python/Flask backend (`plaid-python` SDK) with Plaid Link's web SDK
  (`link-initialize.js` from cdn.plaid.com) in the Jinja page. Re-request implement-phase
  guidance with platform "web (Flask + Plaid Link JS)" at phase 4. The first request used
  the free-form platform string and returned Hosted Link fallback notes, which do not apply
  (HOSTED-*, OAUTH-007).
- Environment: sandbox until acceptance passes. `PLAID_ENV=sandbox` default (DESIGN §5.2).
  Geography: US only.

## Human tasks

Dashboard state read 2026-09-29 via dashboard_get_state (client 6abb0047c2237e000d3ac099).

| Task | Why it matters | Where | State |
|------|----------------|-------|-------|
| Transactions enabled for US production | Link token creation fails with INVALID_PRODUCT without it | https://dashboard.plaid.com/settings/team/products | verified (production_by_country.US includes transactions; authorized_environments: sandbox, production) |
| Register redirect URI `http://localhost:8001/connections/oauth-return` (sandbox) | Without it, OAuth banks (Chase is OAuth-only) are missing from Link or break mid-flow | https://dashboard.plaid.com/developers/api | needs_human (redirect_uris is empty) |
| Register redirect URI `https://general-ledger.hruskagroup.com/connections/oauth-return` (production) | Same, for production; exact match required, no query or fragment | https://dashboard.plaid.com/developers/api | needs_human (redirect_uris is empty) |
| Complete company profile and data-security questionnaire ("Verify business") | Gates Chase OAuth on paid plans. On the free Trial the dashboard says "No action is needed to access banks" | https://dashboard.plaid.com/onboarding-tasks | not_applicable while on Trial (owner saw "Free trial 0/10" and "Automatic bank access", 2026-09-30). Becomes needs_human only if Chase is missing from production Link on Trial, or on upgrading to a paid plan |
| Confirm Data Transparency Messaging / Link customization is complete for production | Incomplete DTM makes `/link/token/create` fail with INVALID_LINK_CUSTOMIZATION | https://dashboard.plaid.com/link | cannot_verify (a `default` customization exists; completeness not readable) |
| Confirm the monthly per-Item Transactions price on your plan | DESIGN §14 Q1: the number to compare against QuickBooks and SimpleFIN | https://dashboard.plaid.com/onboarding-tasks (shown on the last page before Submit request) | not_applicable while on Trial (free, 10 production Items). Plaid publishes no price; it appears only in the upgrade request. Subscription months are UTC calendar months and are not pro-rated |
| Store sandbox and production client_id/secret per CREDENTIALS.md (tier 2, `/etc/general-ledger/plaid.enc`), separate per environment | Keys never go in code, logs or the transcript | https://dashboard.plaid.com/developers/keys | needs_human |
| Webhook receiver URL | Not used by decision (see Decisions made) | — | not_applicable |

## Implementation checklist

Phase 4, per DESIGN §5.2. Rule IDs noted for acceptance.

- [ ] `utils/feeds/plaid_feed.py`: `PlaidConnector` implementing `FeedConnector`; client built
      from `PLAID_ENV` + keys resolved via `utils/credentials.py` (GUIDE-001, GUIDE-004, GUIDE-005)
- [ ] `POST /api/connections/link-token`: `/link/token/create` with `products=["transactions"]`,
      `redirect_uri` always set, `transactions.days_requested` computed as days since the
      earliest `feed_start_date` plus a margin, capped at 730 (TXN-009, OAUTH-002, OAUTH-005)
- [ ] Duplicate-Item guard before exchange: refuse or offer update mode if a live connection
      already exists for the same `institution_id` (ITEM-001, ITEM-011)
- [ ] `POST /api/connections/exchange`: `/item/public_token/exchange`, persist the encrypted
      access token (by `credential_ref`) and `item_id` before responding; never log tokens;
      log `request_id` (GUIDE-002, GUIDE-006, GUIDE-013, GUIDE-015, DATA-001, DATA-006)
- [ ] Store Link `onSuccess`/`onExit` metadata server-side, including `link_session_id`,
      institution_id and error codes (CONV-014, CONV-015)
- [ ] `GET /connections/oauth-return`: persist the link_token across the redirect and re-init
      Link with the same token plus `receivedRedirectUri` (OAUTH-003, OAUTH-004, OAUTH-010)
- [ ] Account mapping from `/accounts/get` (authoritative list); key on
      `persistent_account_id` where present (Chase is a TAN institution), else
      `account_id` + mask/subtype; do not treat `account_id` as immutable (TXN-012)
- [ ] Worker sync: `/transactions/sync` with `count=500`, loop while `has_more`, buffer all
      pages, write bank_txn rows and the cursor in one transaction; on
      `TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION` restart from the starting cursor
      (TXN-001, TXN-002, TXN-007, TXN-011, DATA-007)
- [ ] Sync once right after exchange; an empty first sync is normal; show "importing
      history" from `transactions_update_status` (TXN-003, TXN-008)
- [ ] Handle added / modified / removed per DESIGN §5.2; ignore pending lines; removed ids
      that were never stored are a no-op (TXN-004)
- [ ] Sign normalisation in `normalise()`: Plaid positive = money out (TXN-005, DESIGN §5.4);
      fixture per account kind
- [ ] Fields: `merchant_name` (not `name`), `personal_finance_category` pinned to v2 for
      `provider_category`, `include_original_description: true` for the raw
      `description`; handle null merchant/category (TXN-006, TXN-013, TXN-023)
- [ ] Balances from `/accounts/get` after each sync into `bank_account.reported_balance`;
      never call `/accounts/balance/get` (BAL-001, SELECT-005)
- [ ] Item health on each daily sync via `/item/get`: error → `LOGIN_REQUIRED`,
      `consent_expiration_time` → `consent_expires_at`, 14-day warning (ITEM-010, OAUTH-009)
- [ ] Error handling on `error_type` + `error_code`; backoff with jitter for
      INSTITUTION_DOWN / NOT_RESPONDING / PRODUCT_NOT_READY / RATE_LIMIT_EXCEEDED; no retry
      for ITEM_LOGIN_REQUIRED etc. (ITEM-002, ITEM-004, ITEM-013, PITFALL-005)
- [ ] Reconnect: update mode with existing access token, empty `products`, `redirect_uri`
      set; no exchange on success; never delete-and-relink (ITEM-003, OAUTH-005)
- [ ] Disconnect: `/item/remove`, then purge token; ITEM_NOT_FOUND purges and requires
      fresh Link (ITEM-005)
- [ ] Tests: `/sandbox/public_token/create` for backend tests; `user_transactions_dynamic`
      for added/modified/removed; `/sandbox/item/reset_login` for reconnect; Platypus OAuth
      Bank (ins_127287) for the redirect (SANDBOX-003, SANDBOX-004, SANDBOX-009, TXN-014, OAUTH-008)

## Acceptance

- Not started: Plaid is phase 4. Run build_check_acceptance when the checklist is done.

## Maintenance

This integration is maintained with the Plaid MCP; this file is its durable
state. Agents working in this repository: consult build_guidance before
modifying any Plaid-touching code, and re-run build_check_acceptance before
reporting such a change as working. The acceptance above applies only to
the code as it was verified — later changes invalidate it.

## How to test

To be written at phase 4, one block per feature (link, sync, reconnect, disconnect),
with sandbox credentials (`user_good` / `pass_good`, `user_transactions_dynamic`).

## Decisions made

- Plan: **free Trial** (10 production Items, no business verification needed for bank
  access). Seen on the owner's dashboard 2026-09-30. Removing an Item does NOT return its
  slot, so all development and testing runs in Sandbox, and Chase is linked in production
  exactly once, from the finished app. Upgrade to Pay-as-you-go (verify business, submit
  request) only if Chase is missing from production Link on Trial.

- Product stack: transactions only. Confirmed by the owner 2026-09-29.
- Sync trigger: **daily poll at 06:00 Central plus "Sync now"**, no webhook receiver.
  Confirmed by the owner 2026-09-29, per DESIGN §5.2 (the server accepts no inbound calls
  without a reviewed exception). This is a deliberate deviation from Plaid's
  webhook-first guidance (WEBHOOK-005, TXN-003, WEBHOOK-006). Mitigations: daily
  `/item/get` for errors and consent expiry, `transactions_update_status` in the sync
  response, and a manual "Sync now". Cost: new lines arrive up to a day late, and
  PENDING_DISCONNECT warnings are replaced by the consent-expiry check. Revisit if an
  inbound exception is ever approved.
- Build order: follow DESIGN §13; Plaid lands in phase 4. Confirmed by the owner 2026-09-29.
- Route paths, as specified in DESIGN §2 and §5.2 (GUIDE-020):
  `POST /api/connections/link-token`, `POST /api/connections/exchange`,
  `GET /connections/oauth-return`.
- Link product placement: `products=["transactions"]`, no other slots (CONV-002, TXN-021).

## Open questions

- Verification needs: undecided (earlier answer "None, Account ownership"). Not needed
  for linking the owner's own accounts; account ownership would add identity (SELECT-004).
- Money movement: none at first, "from there we shall see". Adding it later means an
  update-mode re-consent and a new product (auth or transfer). Re-run the Plaid scope step first.
- Are Chase checking and the Ink card under one Chase login (one Item or two)? DESIGN §14 Q2.
- Does Chase appear in production Link for this team? The Trial's "Automatic bank access"
  panel shows what looks like Chase's logo, so probably yes; confirmed only at the one
  production link in phase 4. DESIGN §14 Q1.
