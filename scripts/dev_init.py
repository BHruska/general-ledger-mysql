#!/usr/bin/env python3
"""
General Ledger v0.1.0
File: scripts/dev_init.py
Description: One-time local setup before the first `docker compose -f compose.dev.yml up`.
             Standard library only, so it runs before any virtualenv exists.

Creates, if missing:
  .devdata/                      the container's /data. Created here rather than by
                                 Docker, which would create it as root on Linux/WSL
                                 and leave UID 1000 unable to write to it.
  .devsecrets/                   the container's /etc/general-ledger (read-only mount)
  .devsecrets/session_secret     a random DEV-ONLY signing key for the session cookie

Never overwrites anything, and never prints a secret. Production gets its own key via
`python credential.py set session_secret --encrypted` (docs/CREDENTIALS.md).
"""

import os
import secrets
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    data = ROOT / ".devdata"
    secrets_dir = ROOT / ".devsecrets"
    for directory in (data, secrets_dir):
        created = not directory.exists()
        directory.mkdir(exist_ok=True)
        print(f"{'created ' if created else 'exists  '} {directory.relative_to(ROOT)}/")
    try:
        secrets_dir.chmod(stat.S_IRWXU)  # 700; a no-op on Windows ACLs
    except OSError:
        pass

    key_file = secrets_dir / "session_secret"
    if key_file.exists():
        print("exists   .devsecrets/session_secret (left as is)")
        return 0

    # Owner-only from creation, never chmod-ed after the fact.
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
    try:
        os.write(fd, (secrets.token_hex(32) + "\n").encode("ascii"))
    finally:
        os.close(fd)
    print("created  .devsecrets/session_secret (random, dev only, gitignored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

""" EOF - dev_init.py """
