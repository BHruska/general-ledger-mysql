# Building a new app to drop into the Photon stack

How to structure an application repo from its first commit so that adding it to
the Photon server is a configuration change rather than a port.

**Revision 2 — 2026-09-23, from the infra repo.** Most of this is
`docs/HPQ-INTEGRATION.md` generalised. That app began on SQLite, with its own
Compose file and its state spread across a VM, and each of those had to be
undone before it could be deployed. Everything below exists to stop the next app
repeating it. Revision 2: inbound webhooks are possible after all, as a
reviewed exception (§1 rule 5, §6).

Throughout, replace:

| Placeholder | Meaning | Example |
| --- | --- | --- |
| `<app>` | repo, service, container and hostname name — hyphens fine | `hpq-dashboard` |
| `<app_db>` | MySQL database and user name — **underscores, no hyphens** | `hpq` |

A hyphen in a MySQL identifier is legal but must be backquoted in every
statement forever, including in other people's ad-hoc queries. Use underscores
and the problem never exists.

The short version:

1. The app repo ships a **`Dockerfile`** and nothing else about production. The
   infra repo owns the Compose service, nginx, TLS, auth, env file and backups.
2. **The real database engine from the first commit, including in tests.** The
   server runs MySQL 8.0, so development does too — via a `compose.dev.yml` in
   the app repo that runs the same image with the same database name, user and
   URL shape. There is no second engine to keep in sync and nothing to port.
3. **The app gets its own database** on the shared server, not tables in
   `appdb`.
4. **All state is in MySQL or under one `/data` directory.** Credentials are a
   read-only file mount or environment variables, never files in the repo.

---

## 0. Names

Settle these before the infra side writes anything, so nothing has to be renamed
afterwards.

| Thing | Convention | Yours |
| --- | --- | --- |
| GitHub repo, and the clone on the server | `<app>` → `/opt/apps/<app>` | |
| Compose service and container | `<app>` | |
| Internal port | 8000 for the Flask apps; 8080 for hpq | |
| nginx upstream | `http://<app>:8000` | |
| Public hostname | `<app>.hruskagroup.com` | |
| Data directory (bind mount) | `/opt/data/<app>` → `/data` | |
| Secret files, if any | `/opt/data/secrets/<app>` → `/etc/<app>:ro` | |
| MySQL database | `<app_db>` | |
| MySQL user | `<app_db>`, granted on `<app_db>.*` only | |
| Env file (infra repo) | `env/<app>.env` | |
| Make targets | `up-<short>`, `logs-<short>`, `redeploy-<short>` | |

**The clone on the server must use the repo name above**, even if your local
working copy is called something else. Compose builds with
`context: ../<app>`, which resolves against the server's directory name, so
`git clone <url> <app>` — never let git name the directory, and never assume the
local name.

---

## 1. The server this lands on

```
/opt/apps/
├─ photon-docker-infra/   compose file, nginx config, Makefile, env files
├─ market-dashboard/      app repo: Dockerfile, no compose file
├─ trade-dashboard/       app repo: Dockerfile, no compose file
├─ hpq-dashboard/         app repo: Dockerfile, no compose file
└─ <app>/                 this one, on the same terms
/opt/data/                all persistent state, as bind mounts
```

| Service | Internal name | Port | Published? |
| --- | --- | --- | --- |
| MySQL 8.0 | `db` | 3306 | no |
| market / trade dashboards | `market-dashboard`, `trade-dashboard` | 8000 | no |
| hpq dashboard | `hpq-dashboard` | 8080 | no |
| phpMyAdmin | `phpmyadmin` | 80 | no |
| nginx | `nginx` | 80/443 | **yes, the only one** |

Everything shares one Compose network and reaches everything else by service
name. The server uses Compose **v1** (`docker-compose`, hyphenated), and every
Makefile target pins the compose file with `-f`.

### Rules the container must follow

1. **Only nginx publishes ports.** The service uses `expose:` in production. A
   `ports:` entry bypasses the password gate entirely, leaving the app open
   while everything still looks protected.
2. **nginx owns TLS and the perimeter password.** Every vhost sits behind HTTP
   Basic Auth shared across all hostnames. The app implements neither.
3. **All persistent state is in MySQL or under `/opt/data`.** Anything else is
   not backed up, and nothing will warn you.
4. **Secrets never enter the app repo or the image.** Env files live in the
   infra repo's gitignored `env/`; key files live under `/opt/data/secrets/`.
5. **Nothing external can reach the app except through nginx**, from two known
   networks. **Prefer polling or outbound connections** (outbound HTTPS and WSS
   work) over inbound webhooks. A third party *can* call in, but only as an
   exception the infra side builds per path: a FortiGate policy for the
   sender's published addresses, and an exact-match nginx `location` with
   Basic Auth off. market-dashboard's TradingView receiver is the worked
   example (`docs/ALERT-RECEIVER.md` in the infra repo). If you need one, see
   "If the app receives webhooks" in §6 before writing the endpoint.
6. **Comments explain why, not what.** If a line exists because something broke,
   say what broke.

---

## 2. The database: shared server, private database

### Why its own database rather than tables in `appdb`

- **Isolation without another server.** A second MySQL container would need its
  own backups, health checks, patching and phpMyAdmin wiring. A separate
  *database* gets all of that for free, with no table-name collisions with the
  dashboards. `hpq` did the same, for the same reason: `trades` is too generic a
  name to share a schema with anyone.
- **Backups are automatic.** `scripts/backup-volumes.sh` lists databases with
  `SHOW DATABASES` and runs `mysqldump --single-transaction` over all of them
  nightly. A new database is included with no change to the script.
- **Its own user, granted only on its own database.** The three dashboards share
  `appuser`. Prefer a per-app user: a leaked `DATABASE_URL` from another app
  then cannot read or rewrite this app's data, and this app's cannot touch
  theirs. The cost is two extra lines in §7.

### What the app may and may not assume

| The app may | The app must not |
| --- | --- |
| Create, alter and drop **tables** in `<app_db>` | `CREATE DATABASE`: it exists already, and the user cannot create one |
| Run its own migrations at startup | Need `SUPER`, `SET GLOBAL` or any server-wide setting |
| Rely on MySQL 8.0 defaults (strict mode, utf8mb4) | Assume it is the only client of the server |
| Hold connections open for days | Assume a connection survives `db` restarting |

### Local development: `compose.dev.yml` in the app repo

This is the answer to "how do I develop against a shared MySQL I cannot reach":
run the same image locally, set up the same way.

The filename is deliberate. `docker compose up` and `docker-compose up` only
auto-discover `compose.yaml`, `compose.yml`, `docker-compose.yaml` and
`docker-compose.yml`, so `compose.dev.yml` is never picked up by accident, and
nobody can start it on the server as a second Compose project. That matters: a
second project gets its own network, and nginx could not resolve the app by
name. `hpq-dashboard` shipped a `docker-compose.yml` and had to delete it for
exactly that reason.

```yaml
# compose.dev.yml -- LOCAL DEVELOPMENT ONLY. Production is defined in the
# photon-docker-infra repo; this file is never used on the server.
#   docker compose -f compose.dev.yml up --build
name: <app>-dev

services:
  db:
    # Same tag as production. Do not upgrade this independently: a feature that
    # exists in 8.4 but not 8.0 would pass here and fail on the server.
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: devroot
      MYSQL_USER: <app_db>
      MYSQL_PASSWORD: devpass
    volumes:
      - <app>-dev-mysql:/var/lib/mysql
      # Runs only on the first start with an empty volume. Mirrors the SQL the
      # infra side runs on the server (section 7), so grants match production.
      - ./docker/dev-initdb:/docker-entrypoint-initdb.d:ro
    ports:
      # Loopback only, and 3307 so it does not collide with a MySQL already on
      # the workstation. For tests and a SQL client on the host.
      - "127.0.0.1:3307:3306"
    healthcheck:
      test: ["CMD-SHELL", "mysqladmin ping -h localhost -p$${MYSQL_ROOT_PASSWORD} || exit 1"]
      interval: 5s
      timeout: 5s
      retries: 20

  <app>:
    build: .
    env_file: [ ./.env.dev ]
    depends_on: { db: { condition: service_healthy } }
    # Dev only. Production uses `expose: ["8000"]` behind nginx.
    ports: [ "127.0.0.1:8000:8000" ]
    volumes:
      - ./.devdata:/data
      - ./.devsecrets:/etc/<app>:ro

  # Only if the app has a background process; see section 3.
  <app>-worker:
    build: .
    command: ["worker"]
    env_file: [ ./.env.dev ]
    depends_on: { db: { condition: service_healthy } }
    volumes:
      - ./.devdata:/data
      - ./.devsecrets:/etc/<app>:ro
    stop_grace_period: 60s

volumes:
  <app>-dev-mysql:
```

```sql
-- docker/dev-initdb/01-databases.sql
-- Keep identical to section 7, plus the test database.
CREATE DATABASE IF NOT EXISTS <app_db>      CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS <app_db>_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON <app_db>.*      TO '<app_db>'@'%';
GRANT ALL PRIVILEGES ON <app_db>_test.* TO '<app_db>'@'%';
```

```ini
# .env.dev -- committed; contains nothing secret. Production's equivalent is
# env/<app>.env in the infra repo, and has the same keys.
DATABASE_URL=mysql+pymysql://<app_db>:devpass@db:3306/<app_db>
APP_HTTPS=0
TZ=America/Chicago
```

Gitignore `.devdata/` and `.devsecrets/`. To start from an empty database, run
`docker compose -f compose.dev.yml down -v`; the init script only runs against
an empty volume, so editing it has no effect until you do.

**Tests run against MySQL too.** Point them at
`mysql+pymysql://<app_db>:devpass@127.0.0.1:3307/<app_db>_test` from the host,
or `db:3306` from inside a container. Have a session fixture run the real
migrations into the test database and truncate tables between tests. In CI, a
`mysql:8.0` service container plus the same init SQL gives the same result.
Because no test ever runs on another engine, no test can pass on behaviour
MySQL does not have.

### Schema and driver guidance

- **SQLAlchemy 2.x + Alembic over `mysql+pymysql://`.** Matches the URL spelling
  every other env file on the server uses. Run `alembic upgrade head` from the
  entrypoint, **once, before** the server or worker starts — never from inside
  each gunicorn worker, which would race.
- **Money and quantities are `DECIMAL`, never `FLOAT`/`DOUBLE`.** Keep them as
  Python `Decimal` end to end. PyMySQL already returns `DECIMAL` columns as
  `Decimal`.
- **Timestamps are UTC**, stored as `DATETIME(6)`, with `time_zone = '+00:00'`
  set on connect. `TZ` in the env file is for log readability only; never let it
  reach stored data.
- **Idle connections get dropped.** MySQL closes them after `wait_timeout`
  (8 h), and a background worker will idle overnight. Use
  `create_engine(..., pool_pre_ping=True, pool_recycle=3600)`. `hpq` hit this,
  and SQLite has no equivalent failure, so a SQLite-first design never learns to
  guard against it.
- **`CREATE INDEX IF NOT EXISTS` does not exist in MySQL 8.0.** Declare indexes
  inside `CREATE TABLE`, or let Alembic own them. A bare `CREATE INDEX` run
  twice fails on the *second* startup, not the first.
- **Plan retention before storing anything high-volume.** Records a person reads
  are small and permanent; sampled data, logs and event streams are neither, and
  they share a disk with every other app and are gzipped into `/opt/backups`
  every night. Store the granularity actually used, and prune on a schedule the
  app owns.
- **No stored functions or triggers** without a real need: binary logging is on
  by default in 8.0, so creating functions requires a server-wide setting this
  app cannot change.

---

## 3. What the app repo provides vs. what the infra repo provides

**App repo (`<app>`) provides:**

```
Dockerfile
.dockerignore
.gitattributes              *.sh and Dockerfile as eol=lf
docker/entrypoint.sh        migrations, then the selected role
docker/dev-initdb/01-databases.sql
compose.dev.yml             local only (section 2)
.env.dev                    local only, nothing secret
alembic/ …                  migrations
```

**Infra repo provides; the app repo does not write these:**

- the `<app>` service block in `docker-compose.yml`
- **`<app>` in nginx's `depends_on`**. nginx resolves a literal `proxy_pass`
  hostname once at startup and exits if it cannot, so a missing entry takes
  *every* vhost down, not just this one.
- `nginx/conf.d/<app>.conf`: an open `:80` for ACME, and Basic Auth plus proxy
  headers at `server` level on `:443`
- `env/<app>.env`
- Make targets: up / logs / restart / shell / env / redeploy
- `/opt/data/<app>` in `scripts/backup-volumes.sh`, plus an exclusion if the
  app stores live credentials (§5)
- the health line in `scripts/health.sh`
- the database, user and grants (§7)
- the certificate SAN and the DNS record
- a deploy key: `make add-deploy-key REPO=<app>`

For reference, the service block the container should expect:

```yaml
  <app>:
    build: { context: ../<app>, dockerfile: Dockerfile }
    container_name: <app>
    env_file: [ ./env/<app>.env ]
    depends_on: { db: { condition: service_healthy } }
    expose: [ "8000" ]
    volumes:
      - /opt/data/<app>:/data
      - /opt/data/secrets/<app>:/etc/<app>:ro    # only if there are key files
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 40s
```

### If the app has a background process

A UI and a long-running background job have different lifecycles: restarting the
UI should not interrupt work in flight. Two Compose services built from **one
image**, selected by `command:`, is the default answer, and it is available
precisely because all shared state is in MySQL.

`hpq-dashboard` instead runs everything in one container under supervisord, but
only because its bots and UI share settings files and *file* locks, which work
only inside a single filesystem namespace. If the app has that constraint, copy
that pattern; otherwise prefer two services.

If the UI needs to start or stop the worker, do it through a row in MySQL that
the worker polls — a `desired_state` column. **Never mount the Docker socket**
into a web container: that hands host root to anyone who compromises the UI.

---

## 4. The container contract

| Requirement | Why |
| --- | --- |
| Listens on `0.0.0.0:<port>` | nginx reaches it over the Compose network, not loopback. |
| **`GET /healthz`** → 200, no login, no dependency calls | Docker checks it from inside the container. If the check calls a third party, their outage marks this container unhealthy and sends people looking in the wrong place. Report dependency status on a separate page. |
| `curl` installed | The compose healthcheck and the infra repo's `scripts/health.sh` both exec it inside the container. |
| Config only from env and `/etc/<app>` | The same image runs locally and on the server; nothing environment-specific is baked in. |
| Logs to stdout/stderr | `make logs-<short>` is how an operator watches a deploy. Files under `/data` are an optional extra, never the only copy. |
| Non-root UID, default 1000, set as a build arg | Any read-only secret mount must be readable by that UID. A mismatch looks like a credential error, not a permission one. |
| tini, or `exec` form, as PID 1 | Otherwise `SIGTERM` never reaches the app and Docker `SIGKILL`s it at the end of the grace period. |
| `ProxyFix(x_proto=1, x_host=1)` for Flask | So the app sees `https` and the real host behind nginx. |
| Session cookie `Secure` when `APP_HTTPS=1` | Production sets it; dev does not. |
| No request longer than ~30 s | nginx's default `proxy_read_timeout` is 60 s. Queue slow work. If a long request is unavoidable, the order must be nginx ≥ gunicorn > the app's own ceiling, and the infra side has to be told the number so the vhost can carry it. |
| `.dockerignore` excludes `.env*`, `.dev*`, keys, local databases | Otherwise local secrets and state are baked into the image. |
| `.gitattributes`: `*.sh text eol=lf` | A CRLF entrypoint built on Windows fails with `no such file or directory` for a file that plainly exists. |
| Executable bits via `git update-index --chmod=+x` | A `chmod +x` done on the server blocks every later `git pull` with "local changes would be overwritten". |

### One image, both environments

There is **one `Dockerfile` and no dev variant**. `compose.dev.yml` builds it
with `build: .`; the server builds the same file with
`build: { context: ../<app> }`. So `docker compose -f compose.dev.yml build`
failing locally is the same failure `make redeploy-<short>` would hit, found
before the push rather than during a deploy.

Everything that differs between the two is outside the image:

| | Local (`compose.dev.yml`) | Photon server (infra repo) |
| --- | --- | --- |
| Image | built from this `Dockerfile` | the same, from the same file |
| App port | published on `127.0.0.1` | `expose:` only; nginx publishes 443 |
| Environment | `.env.dev`, committed, no secrets | `env/<app>.env`, gitignored |
| `/data` | `./.devdata` | `/opt/data/<app>` |
| `/etc/<app>` | `./.devsecrets`, dev credentials | `/opt/data/secrets/<app>`, mode 700 |
| Database | `db` container in the dev project | shared `db` service, database `<app_db>` |
| TLS, Basic Auth | none | nginx |

The app must therefore read **every** environment-specific value from the
environment or from `/etc/<app>`. A hostname, path or credential baked into the
image is a value that cannot differ between the two — which is how an image that
works locally fails on the server.

### The Dockerfile

Modelled on `hpq-dashboard`'s, the most recent of the four and the one written
with these constraints in mind.

```dockerfile
# <app>.
# Code only: settings, keys, data and logs live outside the image -- in MySQL,
# under /data, and under /etc/<app>. The Compose service lives in the infra
# repo, not here: a second Compose project on the server would get its own
# network, and nginx could not resolve this service by name.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOME=/data \
    TZ=America/Chicago

# tzdata: slim carries no zoneinfo database, and every time shown is US Central.
# curl:   the compose healthcheck and the infra repo's scripts/health.sh both
#         exec it inside this container, so it is not optional.
# tini:   PID 1 that forwards SIGTERM. Without it a background worker never gets
#         the signal, and Docker SIGKILLs it at the end of stop_grace_period --
#         which is exactly when it is in the middle of something.
# No gcc: SQLAlchemy, PyMySQL and cryptography all ship wheels. Add it back only
#         if a dependency genuinely has to build, and then in a builder stage.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata curl tini \
 && rm -rf /var/lib/apt/lists/*

# The UID must own /opt/data/secrets/<app> on the server, or a read-only key
# mount is unreadable. Confirm with `stat -c '%u %g'` there before the first
# build: a mismatch surfaces as an error that reads like a bad credential.
ARG UID=1000
ARG GID=1000
RUN groupadd -g "${GID}" app \
 && useradd -u "${UID}" -g "${GID}" -m -s /usr/sbin/nologin app \
 # /data must exist and belong to that user before anything mounts over it:
 # Docker creates a missing bind-mount target as root, and the container then
 # cannot write into its own data directory.
 && mkdir -p /data \
 && chown app:app /data

WORKDIR /app

# Dependencies before source, so editing code does not reinstall the world.
COPY --chown=app:app requirements.txt ./
RUN pip install -r requirements.txt

COPY --chown=app:app . /app
RUN chmod +x /app/docker/entrypoint.sh

# Not root from here on. Anything that needs writing is under /data or in MySQL;
# the image itself is read-only in practice.
USER app

EXPOSE 8000

# Deliberately no `VOLUME ["/data"]`: with it, any `docker run` that forgets the
# mount silently leaves an anonymous volume behind holding real state. Both
# compose files always mount /data explicitly.

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://localhost:8000/healthz || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker/entrypoint.sh"]
# Overridden with ["worker"] by the worker service, if there is one.
CMD ["web"]
```

### The entrypoint

One image, several roles, chosen by `command:`. The same file runs locally and
on the server, so a preflight check that fires in dev also fires in production.

```sh
#!/bin/sh
# Container start. "web" (default) serves the app, "worker" runs the background
# process, "migrate" applies migrations and exits; anything else runs as a
# command (e.g. "bash").
set -eu

: "${DATABASE_URL:?DATABASE_URL is not set -- nothing can start without it}"

# Check required credentials here rather than starting and failing every request
# with a message nobody is watching for. One clear line in `docker logs` beats a
# container that looks healthy and cannot do its job.
# e.g.:
#   [ -r "${API_KEY_FILE:-/etc/<app>/key.json}" ] || { echo "..."; exit 1; }

# `depends_on: service_healthy` covers a cold start, but not `db` being
# restarted underneath a running stack, where this container may restart first
# and lose the race. Retry rather than crash-loop into the restart policy.
migrate() {
    n=0
    until alembic upgrade head; do
        n=$((n + 1))
        [ "$n" -lt 10 ] || { echo "Database still unreachable after $n tries; giving up."; exit 1; }
        echo "Database not ready yet (try $n); retrying in 3s..."
        sleep 3
    done
}

case "${1:-web}" in
    web)
        # If there is also a worker, either service may start first, so
        # alembic/env.py wraps the upgrade in SELECT GET_LOCK('<app>-migrate', 60).
        # Two processes migrating concurrently is a corrupted schema, and it only
        # happens on the deploys where a migration exists to apply.
        migrate
        # --timeout stays below nginx's proxy_read_timeout (60s by default on
        # this vhost) and above the app's own slowest request; see the
        # request-duration row in the contract table above.
        exec gunicorn --bind 0.0.0.0:8000 \
                      --workers "${GUNICORN_WORKERS:-2}" \
                      --threads "${GUNICORN_THREADS:-4}" \
                      --timeout 45 \
                      --access-logfile - \
                      "<app_package>.wsgi:app"
        ;;
    worker)
        migrate
        exec python -m <app_package>.worker
        ;;
    migrate)
        migrate
        ;;
    *)
        exec "$@"
        ;;
esac
```

`.dockerignore` must exclude `.env*`, `.devdata/`, `.devsecrets/`, `.git/`,
`__pycache__/` and any key file. Without it, a build bakes local credentials and
local state into the image.

### Running it the way the server does

```bash
docker compose -f compose.dev.yml up --build -d
docker compose -f compose.dev.yml exec <app> curl -fsS http://localhost:8000/healthz
docker compose -f compose.dev.yml ps          # same healthy/unhealthy column as `make status`
docker compose -f compose.dev.yml logs -f <app>
docker compose -f compose.dev.yml run --rm <app> migrate
```

Two things worth knowing locally:

- **On Linux or WSL, create `.devdata` before the first `up`.** Docker creates a
  missing bind-mount source as root, and the container runs as UID 1000 and
  cannot write into it — the same failure the server's
  `chown -R 1000:1000 /opt/data/<app>` prevents, met earlier. Docker Desktop on
  Windows hides this, which is why it is worth meeting on purpose.
- **A source bind mount for hot reload breaks parity.** If you add `- .:/app` to
  the dev service, the container stops running what the image contains. Always
  do a final `docker compose -f compose.dev.yml up --build` *without* it before
  pushing, or the first thing the server builds is something never run.

### Graceful shutdown

On `SIGTERM`: stop accepting new work, finish or safely abandon what is in
flight, flush to MySQL, and exit within `stop_grace_period` (Docker's default is
10 s; ask the infra side for more if the work needs it, and say why). Test it
with `docker compose -f compose.dev.yml stop <app>-worker` and read the logs.

### Startup reconciliation

`restart: unless-stopped` means the container comes back after a crash, a host
reboot or a redeploy with no memory of what it was doing. If the app acts on an
external system, **that system is the source of truth and the database is the
journal**: on every start, fetch the current state from it and reconcile into
MySQL before making a new decision.

---

## 5. Secrets and external credentials

- **Small values** (passwords, tokens, URLs) go in `env/<app>.env` in the infra
  repo, which is gitignored. The app reads them from the environment.
- **Anything multi-line or file-shaped** (a private key, a PEM, a JSON key file)
  is mounted read-only from `/opt/data/secrets/<app>` at `/etc/<app>`, with the
  path given by an env var such as `API_KEY_FILE`. Directory mode 700, owned by
  the container's UID; files 600. Cramming a PEM into an env var invites
  quoting and newline corruption that surfaces as an authentication failure.
- **Live credentials are excluded from the nightly tarball**, the way
  `secrets/hlbot` already is in `scripts/backup-volumes.sh`. A copy on the same
  box protects against nothing and hands the account to anyone who can read
  `/opt/backups`. Keep the original in a password manager. (Password *hashes*,
  like the nginx htpasswd, are backed up on purpose — without them a restore
  locks everyone out.)
- **Scope the credential as narrowly as the provider allows**, and prefer a
  separate credential per environment. If an IP allowlist is offered, restrict
  it to the server's egress address.
- **Dev never holds production credentials.** The local stack has its own
  database and cannot see any lock or flag the production stack uses, so nothing
  technical stops two environments acting on one external account. Separate
  credentials are what stops it.

### If the app acts on a real account (trading, payments, anything irreversible)

- **A mode switch, defaulting to safe.** `APP_MODE=paper|live`, `DRY_RUN=1` — the
  unset value must be the harmless one. In dry-run the app does everything
  except the external side effect, and journals what it would have done into the
  same tables with a `mode` column.
- **One writer per account.** On 2026-09-15 two `hpq` processes ran the same bot
  on one account and both acted on the same signal; the damage was a
  double-counted journal row only because one order never filled. Two layers:
  1. **Within the database:** take `SELECT GET_LOCK('<app>-worker:<account>', 0)`
     on a dedicated connection at startup and refuse to act without it. MySQL
     releases the lock if the connection dies, so the app must also stop acting
     if it loses that connection.
  2. **Across environments:** see the credentials rule above.
- **Write the intent before causing the effect.** Generate the idempotency key
  yourself, insert a row with it in a `pending` state, then call the provider.
  A retry after a timeout reuses the key and the provider deduplicates, so a
  network error cannot become a double action. A crash between the insert and
  the call leaves a `pending` row for startup reconciliation to resolve.
- **Rate limits and dropped connections are routine.** Back off and reconnect
  rather than crashing and letting `restart:` do it.

---

## 6. Authentication

Two layers:

1. **nginx Basic Auth**, shared across all vhosts and managed with
   `make auth-add-user`. It covers everything on the hostname, including
   `/healthz` from outside. Nothing expires it: Basic Auth has no session.
2. **The app's own login**, if the app is more than a read-only dashboard. The
   perimeter password is shared by everyone allowed onto any of the sites; it is
   not a per-app identity, and anything that can take an action should have one.
   Cookie `HttpOnly`, `SameSite=Strict`, and `Secure` behind TLS. Every
   state-changing request requires a JSON content type or a CSRF token.

The firewall is a third layer: the FortiGate in front of the box opens 443 to
two known networks, plus the published addresses of any webhook sender.

### If the app receives webhooks

A webhook path has neither of the first two layers -- the sender cannot log in
-- so the app carries all of it:

- **One exact path, named to the infra side.** It gets `location =`, never a
  prefix, so keep anything that reads back what was received (an inspection
  page, a ping) at a *different* path that stays behind Basic Auth. A prefix
  would publish it.
- **A shared secret, compared with `hmac.compare_digest`, failing closed.**
  Unset means reject everything. The firewall allowlist proves the request came
  through the provider, not that it came from you: any of the provider's
  customers can point their webhook at your URL.
- **Header if the provider can send one; query string only if it cannot.** A
  query-string secret lands in every access log that records full URLs. The
  infra side strips it from nginx's log for that location; the app must strip
  it from its own (for gunicorn, `--access-logformat` with `%(U)s` rather than
  the default `%(r)s`) and never store the URL with the payload.
- **Record first, parse later.** Store the raw body before interpreting it,
  answer 2xx to any authenticated request (the provider may retry a failure),
  and parse once real payloads have been seen. If the database is down, fall
  back to a file under `/data` -- for authenticated requests only, or anyone can
  fill the disk.
- **Unauthenticated requests are bounded, not trusted.** nginx rate-limits the
  path per source IP. If the app records rejected requests too, give that table
  a retention job (§2): rejected rows arrive at the provider's rate, not yours.
- **Tell the infra side the sender's published IP list and where it is
  published.** When the provider adds an address, alerts from it are dropped at
  the FortiGate, and nothing appears in any log on the server.

---

## 7. First deployment (infra side)

From `/opt/apps/photon-docker-infra`:

```bash
# 1. Clone under the server name, with a read-only deploy key
make add-deploy-key REPO=<app>

# 2. Data and secrets directories (confirm the UID matches the Dockerfile)
sudo mkdir -p /opt/data/<app> /opt/data/secrets/<app>
sudo chown -R 1000:1000 /opt/data/<app> /opt/data/secrets/<app>
sudo chmod 700 /opt/data/secrets/<app>
#    copy any key files in, mode 600

# 3. Database, user, grant -- `make shell-db`, then:
```

```sql
-- Keep identical to docker/dev-initdb/01-databases.sql in the app repo,
-- minus the test database.
CREATE DATABASE <app_db> CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER '<app_db>'@'%' IDENTIFIED BY '<generated>';
GRANT ALL PRIVILEGES ON <app_db>.* TO '<app_db>'@'%';
```

```bash
# 4. env/<app>.env -- the same keys as .env.dev, with production values:
#      DATABASE_URL=mysql+pymysql://<app_db>:<generated>@db:3306/<app_db>
#      APP_HTTPS=1
#    Strip CRLF if edited on Windows:  sed -i 's/\r$//' env/<app>.env

# 5. DNS, then expand the certificate to cover the new hostname

# 6. Compose service, vhost, depends_on, Makefile targets committed and pulled:
make up-<short>
make up-nginx          # NOT restart-nginx -- depends_on and volumes changed
make status
```

Verify from the server without going out through the firewall, which does not
admit the box itself:

```bash
curl -I --resolve <app>.hruskagroup.com:443:127.0.0.1 \
     -u <user> https://<app>.hruskagroup.com/
```

The next nightly backup should list `<app_db>` on its `databases:` line with no
change to the script.

---

## 8. Sequencing

1. **App repo, entirely local:** Dockerfile, `compose.dev.yml`, migrations, the
   app itself, tests against the dev MySQL. Nothing on the server is needed.
2. **App repo:** graceful shutdown, startup reconciliation, and any single-writer
   guard. Prove each by killing and restarting the container mid-operation.
3. **Infra repo:** everything listed in §3.
4. **Server:** §7, in the safe mode first if the app has one.
5. **Going live** is then an env change plus `make up-<short>` — `up`, not
   `restart`: env, volume and `depends_on` changes need the container recreated,
   and `docker-compose restart` never re-reads the compose file.

Steps 1 and 2 can land on the app's main branch at any time. Nothing on the
server pulls them until someone redeploys.

---

## 9. Checklist before asking for the infra change

- [ ] §0 filled in and agreed
- [ ] `docker compose -f compose.dev.yml up --build` works from a clean clone
- [ ] Tests pass against MySQL, with no other engine anywhere in the repo
- [ ] `GET /healthz` answers 200 with no login and no third-party call
- [ ] Container runs as non-root; UID confirmed against the server
- [ ] `SIGTERM` shuts down cleanly within the grace period you are asking for
- [ ] No `ports:`, no Compose file that the server could pick up, no Docker socket
- [ ] Nothing environment-specific baked into the image
- [ ] `.dockerignore` and `.gitattributes` in place; exec bits set in the tree
- [ ] Any request that can exceed 30 s is named, with its ceiling, for the vhost
- [ ] Retention policy for any table that grows without bound
- [ ] Any inbound webhook: one exact path, a fail-closed secret kept out of the
      app's logs, and the sender's published IP list handed to the infra side
