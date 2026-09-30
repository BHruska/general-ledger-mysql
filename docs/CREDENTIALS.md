# Handling secrets in these apps

Where a credential lives, how it gets there, and how code reads it — decided once,
so no project has to work it out again.

**Revision 1 — 2026-09-20.** Written after `trade-portfolio` needed somewhere to put a
Bitcoin extended public key and the answer took an afternoon of research that should
not have been necessary. The three patterns already in this tree —
`ccxt/_UTILITIES.py`, `trade-marketdashboard/utilities.py` and
`trade-solana/trade_solana/keystore.py` — were all correct for their own contexts and
had no shared rule connecting them. This is that rule.

Companion to [NEW-APP-INTEGRATION.md](NEW-APP-INTEGRATION.md) §5, which this expands
on. Where the two disagree, the integration doc governs deployment and this governs
code.

Throughout, replace:

| Placeholder | Meaning | Example |
| --- | --- | --- |
| `<app>` | repo, service and container name | `trade-portfolio` |
| `<APP>` | the same, upper snake case | `TRADE_PORTFOLIO` |
| `<ref>` | the *name* of one credential, never its value | `arculus1`, `coinbase_ro` |

The short version:

1. **Classify the secret first** (§1). What it costs when it leaks decides everything
   else, and it takes ten seconds.
2. **Three storage tiers, in strength order: OS keyring, encrypted file, plain
   file/env** (§2). Code resolves strongest-first and warns on the weak ones.
3. **The database and the repo store the `<ref>`, never the value.** No exceptions.
4. **Copy `utils/credentials.py` (§6) rather than writing this again.**

---

## 1. Classify the secret

Everything downstream follows from one question: **what does an attacker gain by
reading this?**

| Class | Examples | Leak costs you | Minimum tier |
| --- | --- | --- | --- |
| **Spending** | private keys, seed phrases, exchange keys with trade or withdrawal rights | money, irreversibly | keyring or encrypted file, always |
| **Acting** | API keys that can place orders, send mail, post | actions taken as you | keyring or encrypted file |
| **Reading** | read-only API keys, DB passwords, xpub/zpub | data exposure, usually privacy | encrypted file on a server; plain file acceptable in dev |
| **Identifying** | account numbers, wallet addresses, usernames | correlation, not access | plain storage is fine; keep out of public repos |

Two rules that come straight out of that table:

- **Never hold a spending credential you do not need.** A portfolio tracker needs no
  trading rights; a price fetcher needs no account at all. Scope the credential at the
  provider before deciding where to store it — the cheapest secret to protect is the
  one you never had.
- **An extended public key (xpub/zpub/dgub) is a Reading secret, not an Identifying
  one.** It cannot spend, so it is not in the top class, but it reveals every address
  and the entire transaction history of that wallet forever. Treat it like a database
  password, not like an account number.

---

## 2. The three tiers

### Tier 1 — OS keyring

Windows Credential Manager, macOS Keychain, Linux Secret Service, via the `keyring`
package.

- **Use for:** anything on a developer workstation.
- **Protects against:** a plaintext file sitting in a project folder, a secret swept
  into a synced folder or a backup, an accidental `git add -A`.
- **Does not protect against:** anything running as you.
- **Unattended?** Yes, no passphrase.
- **Available in a container? No** — and that includes a container on your own
  workstation. Linux Secret Service needs D-Bus and a session; a container has
  neither, and it certainly cannot reach Windows Credential Manager on the host.

  **So an app that always runs in Docker cannot use this tier at all, even in
  development.** Verified on 2026-09-20: inside `trade-portfolio`'s dev container
  `keyring` imports fine and then resolves nothing, falling through to the plain
  file. This is easy to get wrong, because the developer's own shell *can* reach the
  keyring — so a credential looks safely stored right up until the app tries to read
  it.

  Tier 1 therefore serves **natively-run tools**: CLIs, scripts, and the credential
  helper that writes the value in the first place. For a containerised app it is tier
  2 or tier 3, and nothing else. This is the single fact that makes tier 2 exist.

**Naming, already established in `ccxt/_UTILITIES.py` — keep it:**

```python
keyring.set_password("WALLET:%s" % ref, "public_key", value)   # wallet keys
keyring.set_password("<APP>:%s" % ref, "secret", value)        # everything else
```

### Tier 2 — encrypted file

Argon2id → AES-256-GCM. Format in §5. Two implementations of the same format:
`trade-solana/trade_solana/keystore.py` (wraps a keypair) and
`trade-portfolio/utils/keystore.py` (wraps arbitrary text — an xpub, an API key).

- **Use for:** servers and containers, where tier 1 is unavailable.
- **Protects against:** a leaked backup tarball, a stolen disk, read access to the
  data volume alone.
- **Unattended?** Yes, with the passphrase in the environment.

**This only works if the passphrase and the ciphertext live in different places.**
On the Photon server they naturally do:

| | Path | Backed up? |
| --- | --- | --- |
| ciphertext | `/opt/data/secrets/<app>/<ref>.enc` | tree is backed up; `secrets/` excluded |
| passphrase | `env/<app>.env` in the infra repo clone | not in the data backup |

An attacker needs both. If the backup exclusion is ever misconfigured — exactly the
kind of thing that fails quietly — the tarball then holds ciphertext instead of your
secret. Put the passphrase and the ciphertext in the same directory and you have
achieved nothing; be honest about that rather than shipping reassuring theatre.

### Tier 3 — plain file or environment variable

The [NEW-APP-INTEGRATION.md](NEW-APP-INTEGRATION.md) §5 baseline: small values in
`env/<app>.env`, file-shaped values mounted read-only at `/etc/<app>`.

- **Use for:** Reading-class secrets in development, and as the fallback that keeps a
  fresh clone working.
- **Always log a warning when a credential resolves from this tier.** Silent plaintext
  is how a dev shortcut reaches production.
- **Never for Spending or Acting secrets.**

---

## 3. The decision table

This is the part that exists so nobody researches this again.

| Where is the code running? | Class | Use |
| --- | --- | --- |
| Workstation, **natively** (a CLI or script) | any | **Tier 1, OS keyring** |
| Workstation, **in a container** | Spending or Acting | **Tier 2**; tier 1 is unreachable |
| Workstation, **in a container** | Reading | **Tier 3**, gitignored, with the warning |
| Server / container | Spending or Acting | **Tier 2, encrypted file** |
| Server / container | Reading | **Tier 2**, or tier 3 with a logged warning |
| CI | any | the CI provider's own secret store, never a file in the repo |
| A fresh clone with nothing configured | any | tier 3, warn, and keep working |

**Build the tier you can use now**, but understand what "now" means. An encrypted
tier written months before deployment is untested code protecting nothing — *unless*
the plaintext alternative is already holding something worth protecting. In
`trade-portfolio` the deciding fact was a zpub for a wallet holding 2.5 BTC sitting in
a plaintext file: at that point "we'll do it at deploy time" is deferring the work past
the moment it started to matter.

Two questions settle it: **how much does the plaintext expose today**, and **will
anyone remember to finish it later?**

**But check which tiers your app can actually reach before planning around one.** A
containerised app has exactly two options, and the more convenient of the three is not
one of them.

---

## 4. Rules that always apply

Independent of tier, and not negotiable:

1. **The database and the repo store the `<ref>`, never the value.** A row says
   `credential_ref = 'arculus1'`; the value is resolved at use.
2. **Never log a secret, and never echo one into a chat, a terminal transcript or an
   error message.** To confirm *which* credential loaded, log a fingerprint — the
   first eight hex of its SHA-256 — never a prefix of the value itself.
3. **`.gitignore` the secret paths before creating them**, not after. A secret
   committed once is in the history forever; the fix is rotation, not `git rm`.
4. **Files are mode 600, directories 700**, owned by the container UID.
5. **Live credentials are excluded from backups** (`scripts/backup-volumes.sh`). A copy
   on the same box protects against nothing. Password *hashes*, like nginx htpasswd,
   are backed up on purpose — without them a restore locks everyone out.
6. **Separate credentials per environment.** Dev must never hold production keys;
   nothing technical stops two environments acting on one account, so separate
   credentials are what stops it.
7. **Scope at the provider first.** Read-only where reading is all you do; IP-allowlist
   to the server's egress address where offered.
8. **Rotation is a supported operation, not an incident.** If you cannot replace a
   credential without editing code, the design is wrong.
9. **Never accept a seed phrase or private key in a UI that does not need one**, and
   say so on the form. Refuse key-shaped input explicitly rather than failing
   validation with "invalid address", which just invites a second attempt.

---

## 5. The encrypted file format (v1)

From `trade-solana/trade_solana/keystore.py`. JSON:

```json
{
  "version": 1,
  "kdf": "argon2id",
  "kdf_params": {"memory_cost_kib": 262144, "iterations": 3, "lanes": 4, "salt": "<b64>"},
  "cipher": "aes-256-gcm",
  "nonce": "<b64>",
  "ciphertext": "<b64>",
  "label": "<non-secret identifier, e.g. a pubkey>",
  "created_at": "<iso8601>"
}
```

Five details that matter, each for a reason:

- **The header is bound in as AES-GCM associated data.** Swapping in weaker KDF
  parameters or editing the recorded label then makes decryption *fail* rather than
  silently succeed. This is the part hand-rolled keystores usually miss.
- **KDF parameters are stored per file**, so raising the defaults later does not break
  existing files.
- **Argon2id at 256 MiB / 3 iterations / 4 lanes** — RFC 9106's second profile, scaled
  up. About 0.3 s per unlock: trivial once at start, expensive to brute force.
- **Write atomically:** to `.tmp`, `chmod`, then `replace()`. A crash mid-write must
  not leave a truncated keystore.
- **Zero the plaintext buffer after use.** Best effort — Python cannot guarantee
  earlier copies are gone — but it costs nothing.
- **A malformed header must raise a keystore error, not a library exception.** Tampered
  KDF parameters can be values Argon2 rejects outright (memory cost below `8 × lanes`,
  for instance), and that surfaced as a raw `ValueError` escaping from the middle of a
  sync until it was caught.

Verified behaviour, worth reproducing in any port. All of these are rejected:
weakened memory cost, reduced iterations, a rewritten label, a swapped salt, a flipped
ciphertext byte, a bumped version, a downgraded cipher, and the wrong passphrase. The
last two produce the *same* message on purpose — distinguishing "wrong passphrase" from
"file modified" tells an attacker which half they got right.

Cost on a 2026 workstation: about 1.0 s to write, 0.5 s to read, 256 MiB transient.
Fine at credential-resolution frequency; do not put it in a request path.

---

## 6. The reusable module

Copy `utils/credentials.py` and `utils/keystore.py` into the project. Together they
implement §2 and §3: resolve strongest-first, warn on weak tiers, never log a value.

```python
from utils import credentials

zpub = credentials.get("arculus1", kind="wallet")     # tier 1 -> 2 -> 3
credentials.describe("arculus1")
# {'ref': 'arculus1', 'source': 'keyring', 'fingerprint': 'a3f9c210', 'weak': False}

credentials.put_keyring("arculus1", zpub, kind="wallet")          # native tools
credentials.write_encrypted("arculus1", zpub, passphrase)         # containers, servers
```

And a CLI, so a secret never passes through shell history or a terminal transcript:

```bash
python credential.py set <ref> --encrypted   # hidden prompt -> keystore
python credential.py encrypt <ref>           # convert an existing plaintext file
python credential.py passwd                  # re-key every keystore, all or nothing
python credential.py list                    # every ref the database expects, and where
                                             # each resolves from, by fingerprint
```

`encrypt` verifies the keystore reads back **before** deleting the plaintext. An
unreadable keystore plus a deleted original is how a credential is lost during the
migration meant to protect it.

`describe()` exists so an operator can confirm *which* credential is loaded, and how
strongly it is held, without the value ever reaching a screen or a log.

---

## 7. Checklist for a new credential

- [ ] Classified (§1), and scoped as narrowly as the provider allows
- [ ] `<ref>` chosen; only the `<ref>` appears in the database and the repo
- [ ] Storage tier chosen from §3 for each environment it runs in
- [ ] Path gitignored **before** the file was created
- [ ] Dev and production values are different
- [ ] Excluded from the nightly backup if it is a live credential
- [ ] Resolution warns when it falls back to tier 3
- [ ] Nothing logs the value; `describe()` used where confirmation is needed
- [ ] Rotation tested once, on purpose
- [ ] For an encrypted credential: the passphrase is in a **different tree** from the
      ciphertext, and a tamper test was run at least once against the format

---

## 8. `CLAUDE.md` snippet

```markdown
## Secrets (see docs/CREDENTIALS.md — binding)

- The database and repo store a credential's NAME (`credential_ref`), never its value.
- Resolve through `utils/credentials.py`, which tries OS keyring, then encrypted file,
  then plain file/env, and warns on the last. Never read a secret path directly.
- 🚨 Never log, print or echo a secret. Use `credentials.describe()`, which returns a
  SHA-256 fingerprint, when you need to confirm which credential is loaded.
- Containers have no OS keyring — that is why the encrypted-file tier exists.
- An xpub/zpub cannot spend but exposes a wallet's entire history: treat it as a
  read-class secret, like a database password.
- Gitignore a secret path before creating the file. A committed secret is rotated,
  not deleted.
```

<!-- EOF - CREDENTIALS.md -->
