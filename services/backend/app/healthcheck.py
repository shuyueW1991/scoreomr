"""Container health probe for the worker (used by Docker HEALTHCHECK)."""
from __future__ import annotations

import sys
from datetime import timedelta

from .config import Settings
from .db import Database
from .timeutil import parse, utcnow


def main() -> int:
    try:
        settings = Settings.from_env()
        db = Database(settings.database_path)
        state = db.get_state("worker")
    except Exception as exc:  # noqa: BLE001
        print(f"worker unhealthy: {exc}")
        return 1
    if not state:
        print("worker unhealthy: no heartbeat yet")
        return 1
    last = parse(state.get("updated_at"))
    if last is None or utcnow() - last > timedelta(seconds=120):
        print(f"worker unhealthy: last heartbeat {state.get('updated_at')}")
        return 1
    print(f"worker healthy: {state.get('updated_at')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
