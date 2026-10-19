"""Consistent SQLite backup.

Usage (inside the API container):
    python -m app.backup /data/backups/scoreomr-YYYYmmdd-HHMM.db
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from .config import Settings
from .db import Database


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    settings = Settings.from_env()
    if argv:
        destination = Path(argv[0])
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = settings.data_dir / "backups" / f"scoreomr-{stamp}.db"
    db = Database(settings.database_path)
    if not settings.database_path.exists():
        print(f"database not found: {settings.database_path}")
        return 1
    path = db.backup_to(destination)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
