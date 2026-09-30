# general-ledger.
# Code only: settings, keys, data and logs live outside the image -- in MySQL,
# under /data, and under /etc/general-ledger. The Compose service lives in the
# infra repo, not here: a second Compose project on the server would get its own
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
# tini:   PID 1 that forwards SIGTERM. Without it the worker never gets the
#         signal, and Docker SIGKILLs it at the end of stop_grace_period --
#         which is exactly when it is mid-sync.
# No gcc: SQLAlchemy, PyMySQL, cryptography and argon2-cffi all ship wheels.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata curl tini \
 && rm -rf /var/lib/apt/lists/*

# The UID must own /opt/data/secrets/general-ledger on the server, or a
# read-only key mount is unreadable. Confirm with `stat -c '%u %g'` there before
# the first build: a mismatch surfaces as an error that reads like a bad
# credential rather than a permission one.
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

# Not root from here on. Anything that needs writing is under /data or in MySQL.
USER app

EXPOSE 8000

# Deliberately no `VOLUME ["/data"]`: with it, any `docker run` that forgets the
# mount silently leaves an anonymous volume behind holding real state.

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://localhost:8000/healthz || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker/entrypoint.sh"]
# Overridden with ["worker"] by the worker service.
CMD ["web"]
