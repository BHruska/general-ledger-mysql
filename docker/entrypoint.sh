#!/bin/sh
# General Ledger v0.1.0
# File: docker/entrypoint.sh
# Description: Container start. "web" (default) serves the app, "worker" runs the
#              background process, "migrate" applies migrations and exits;
#              anything else runs as a command (e.g. "bash", "python manage.py ...").
set -eu

: "${DATABASE_URL:?DATABASE_URL is not set -- nothing can start without it}"

# `depends_on: service_healthy` covers a cold start, but not `db` being restarted
# underneath a running stack, where this container may restart first and lose the
# race. Retry rather than crash-loop into the restart policy.
#
# This waits on CONNECTIVITY ONLY, deliberately (the lesson trade-portfolio learned):
# wrapping `alembic upgrade head` in the retry loop retries a broken migration ten
# times and then reports "Database still unreachable", which sends you to look at
# MySQL when the fault is in your own code.
wait_for_db() {
    n=0
    until python - <<'PY'
import os, sys
import sqlalchemy
try:
    sqlalchemy.create_engine(os.environ["DATABASE_URL"]).connect().close()
except Exception as e:
    print(f"  ({type(e).__name__}: {e})", file=sys.stderr)
    sys.exit(1)
PY
    do
        n=$((n + 1))
        [ "$n" -lt 10 ] || { echo "Database still unreachable after $n tries; giving up."; exit 1; }
        echo "Database not ready yet (try $n); retrying in 3s..."
        sleep 3
    done
}

migrate() {
    wait_for_db
    # Either service may start first, so alembic/env.py wraps the upgrade in
    # SELECT GET_LOCK('general-ledger-migrate', 60).
    alembic upgrade head
}

# The session cookie is signed with this. Without it every login would fail, so say
# so once, here, rather than on every request. describe() never prints the value.
require_session_secret() {
    python - <<'PY'
import sys
from utils import credentials
info = credentials.describe("session_secret")
if not info["available"]:
    print("session_secret is missing: " + info["error"], file=sys.stderr)
    print("Dev: run `python scripts/dev_init.py` on the host. Production: "
          "`python credential.py set session_secret --encrypted`.", file=sys.stderr)
    sys.exit(1)
PY
}

case "${1:-web}" in
    web)
        require_session_secret
        migrate
        # --timeout stays below nginx's proxy_read_timeout (60s) and above the app's
        # own slowest request. The only web routes that call out (Plaid link-token and
        # exchange, phase 4) take about a second.
        exec gunicorn --bind 0.0.0.0:8000 \
                      --workers "${GUNICORN_WORKERS:-2}" \
                      --threads "${GUNICORN_THREADS:-4}" \
                      --timeout 45 \
                      --access-logfile - \
                      wsgi:app
        ;;
    worker)
        migrate
        exec python -m worker
        ;;
    migrate)
        migrate
        ;;
    *)
        exec "$@"
        ;;
esac
