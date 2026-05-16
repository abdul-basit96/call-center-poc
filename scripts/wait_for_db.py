"""Block until Postgres accepts connections (used by Docker entrypoint)."""

from __future__ import annotations

import os
import sys
import time

import psycopg2


def main() -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        sys.exit(1)

    max_wait = int(os.getenv("DB_WAIT_SECONDS", "120"))
    interval = float(os.getenv("DB_WAIT_INTERVAL", "2"))

    for elapsed in range(0, max_wait + 1, int(interval)):
        try:
            conn = psycopg2.connect(url)
            conn.close()
            print("Postgres is ready.")
            return
        except psycopg2.Error as e:
            if elapsed >= max_wait:
                print(f"Postgres not ready after {max_wait}s: {e}", file=sys.stderr)
                sys.exit(1)
            print(f"Waiting for Postgres ({elapsed}s)…")
            time.sleep(interval)


if __name__ == "__main__":
    main()
