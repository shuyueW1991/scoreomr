"""SQLite persistence.

Why SQLite here: this is a single-node, low-concurrency service whose hard
problem is a durable job queue, not horizontal write scaling.  WAL mode +
``BEGIN IMMEDIATE`` give exactly those guarantees without a second database
container, and the whole state is one file that can be copied for backup or
moved with the deployment.

All paths stored in the database are relative to ``DATA_DIR`` so that moving
the data directory does not invalidate rows.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from .errors import ActiveJobExists, NotFound, QueueFull
from .timeutil import iso, utcnow

SCHEMA_VERSION = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    anon_id TEXT,
    mode TEXT NOT NULL CHECK (mode IN ('compare', 'audiveris', 'homr')),
    label TEXT NOT NULL,
    input_path TEXT NOT NULL,
    gt_path TEXT,
    result_dir TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'done', 'error')),
    report_json TEXT,
    chosen TEXT,
    confidence REAL,
    needs_review INTEGER NOT NULL DEFAULT 0,
    worker_id TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    heartbeat_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_anon ON jobs(anon_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_running ON jobs(status, heartbeat_at);

CREATE TABLE IF NOT EXISTS service_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    # ------------------------------------------------------------- plumbing
    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self.connect()
        try:
            conn.executescript(SCHEMA)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    # ---------------------------------------------------------------- jobs
    def create_job(
        self,
        *,
        job_id: str,
        anon_id: str,
        mode: str,
        label: str,
        input_path: str,
        gt_path: str | None,
        result_dir: str,
        max_active: int,
        max_queue: int,
        active_since: str,
    ) -> dict[str, Any]:
        now = iso()
        with self.transaction() as conn:
            queued = conn.execute(
                "SELECT COUNT(*) AS n FROM jobs WHERE status = 'queued'"
            ).fetchone()["n"]
            if int(queued) >= max_queue:
                raise QueueFull()

            if max_active > 0:
                active = conn.execute(
                    """SELECT id FROM jobs WHERE anon_id = ? AND status IN ('queued','running')
                       AND created_at >= ? LIMIT 1""",
                    (anon_id, active_since),
                ).fetchone()
                if active:
                    raise ActiveJobExists(active_job=active["id"])

            conn.execute(
                """INSERT INTO jobs(
                       id, anon_id, mode, label, input_path, gt_path,
                       result_dir, status, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?)""",
                (job_id, anon_id, mode, label, input_path, gt_path, result_dir, now),
            )
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(row)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.read() as conn:
            return self._dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())

    def list_jobs(self, *, anon_id: str | None, limit: int = 20) -> list[dict[str, Any]]:
        with self.read() as conn:
            if anon_id:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE anon_id = ? ORDER BY created_at DESC LIMIT ?",
                    (anon_id, limit),
                ).fetchall()
            else:
                rows = []
            return [dict(row) for row in rows]

    def active_jobs(self, *, anon_id: str | None, since: str) -> int:
        with self.read() as conn:
            if anon_id:
                row = conn.execute(
                    """SELECT COUNT(*) AS n FROM jobs WHERE anon_id = ?
                       AND status IN ('queued','running') AND created_at >= ?""",
                    (anon_id, since),
                ).fetchone()
            else:
                return 0
            return int(row["n"])

    def queue_stats(self) -> dict[str, int]:
        with self.read() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
            ).fetchall()
            counts = {row["status"]: int(row["n"]) for row in rows}
            return {
                "queued": counts.get("queued", 0),
                "running": counts.get("running", 0),
                "done": counts.get("done", 0),
                "error": counts.get("error", 0),
            }

    def claim_next_job(self, worker_id: str) -> dict[str, Any] | None:
        now = iso()
        with self.transaction() as conn:
            for _ in range(3):
                row = conn.execute(
                    "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
                ).fetchone()
                if row is None:
                    return None
                updated = conn.execute(
                    """UPDATE jobs SET status = 'running', started_at = COALESCE(started_at, ?),
                           heartbeat_at = ?, worker_id = ?, attempts = attempts + 1
                       WHERE id = ? AND status = 'queued'""",
                    (now, now, worker_id, row["id"]),
                )
                if updated.rowcount == 1:
                    claimed = conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()
                    return dict(claimed)
            return None

    def touch_job(self, job_id: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE jobs SET heartbeat_at = ? WHERE id = ? AND status = 'running'",
                (iso(), job_id),
            )

    def complete_job(
        self,
        job_id: str,
        *,
        report: dict[str, Any],
        chosen: str | None,
        confidence: float,
        needs_review: bool,
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                """UPDATE jobs SET status = 'done', finished_at = ?, heartbeat_at = NULL,
                       report_json = ?, chosen = ?, confidence = ?, needs_review = ?, error = NULL
                   WHERE id = ? AND status = 'running'""",
                (
                    iso(), json.dumps(report, ensure_ascii=False), chosen, confidence,
                    1 if needs_review else 0, job_id,
                ),
            )

    def fail_job(self, job_id: str, error: str) -> None:
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return
            if row["status"] in {"done", "error"}:
                return
            conn.execute(
                """UPDATE jobs SET status = 'error', finished_at = ?, heartbeat_at = NULL,
                       error = ? WHERE id = ?""",
                (iso(), error[:8000], job_id),
            )

    def stale_running_jobs(self, cutoff: str) -> list[dict[str, Any]]:
        with self.read() as conn:
            rows = conn.execute(
                """SELECT * FROM jobs WHERE status = 'running'
                   AND (heartbeat_at IS NULL OR heartbeat_at < ?) ORDER BY created_at""",
                (cutoff,),
            ).fetchall()
            return [dict(row) for row in rows]

    def requeue_job(self, job_id: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                """UPDATE jobs SET status = 'queued', started_at = NULL, heartbeat_at = NULL,
                       worker_id = NULL WHERE id = ? AND status = 'running'""",
                (job_id,),
            )

    def finish_stale_job(self, job_id: str, message: str) -> None:
        self.fail_job(job_id, message)

    # --------------------------------------------------------- service state
    def set_state(self, key: str, value: dict[str, Any]) -> None:
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO service_state(key, value, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
                (key, json.dumps(value, ensure_ascii=False), iso()),
            )

    def get_state(self, key: str) -> dict[str, Any] | None:
        with self.read() as conn:
            row = conn.execute("SELECT value, updated_at FROM service_state WHERE key = ?", (key,)).fetchone()
            if row is None:
                return None
            try:
                value = json.loads(row["value"])
            except json.JSONDecodeError:
                value = {}
            value["updated_at"] = row["updated_at"]
            return value

    # --------------------------------------------------------------- health
    def health(self) -> dict[str, Any]:
        with self.read() as conn:
            conn.execute("SELECT 1").fetchone()
        state = self.get_state("worker")
        return {
            "db": "ok",
            "queue": self.queue_stats(),
            "worker": state,
        }

    def backup_to(self, destination: str | Path) -> str:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        src = self.connect()
        dst = sqlite3.connect(str(destination))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return str(destination)


def utc_cutoff(**kwargs: float) -> str:
    """Convenience for callers that need an ISO cutoff in the past."""
    return iso(utcnow() - timedelta(**kwargs))


def require_job(job: dict[str, Any] | None) -> dict[str, Any]:
    if job is None:
        raise NotFound("任务不存在")
    return job


def parse_day(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None