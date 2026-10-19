"""SQLite persistence.

Why SQLite here: this is a single-node, low-concurrency service whose hard
problems are atomic daily quotas and a durable job queue, not horizontal
write scaling.  WAL mode + ``BEGIN IMMEDIATE`` give exactly those guarantees
without a second database container, and the whole state is one file that can
be copied for backup or moved with the deployment.

All paths stored in the database are relative to ``DATA_DIR`` so that moving
the data directory does not invalidate rows.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from .errors import ActiveJobExists, NotFound, QueueFull, QuotaExceeded
from .timeutil import iso, utcnow

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    google_id TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    anon_id TEXT,
    ip_hash TEXT,
    mode TEXT NOT NULL CHECK (mode IN ('compare', 'audiveris', 'homr')),
    label TEXT NOT NULL,
    input_path TEXT NOT NULL,
    gt_path TEXT,
    result_dir TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'done', 'error')),
    usage_day TEXT NOT NULL,
    usage_subject TEXT NOT NULL,
    report_json TEXT,
    chosen TEXT,
    confidence REAL,
    needs_review INTEGER NOT NULL DEFAULT 0,
    worker_id TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    refunded INTEGER NOT NULL DEFAULT 0,
    files_deleted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    heartbeat_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_anon ON jobs(anon_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_running ON jobs(status, heartbeat_at);

CREATE TABLE IF NOT EXISTS usage (
    day TEXT NOT NULL,
    subject TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, subject)
);

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
            # Lightweight in-place migration for databases created before
            # Google login was added. New databases already have the columns.
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()
            }
            for name, decl in (("google_id", "TEXT"),):
                if name not in columns:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {name} {decl}")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_id "
                "ON users(google_id) WHERE google_id IS NOT NULL"
            )
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

    # ---------------------------------------------------------------- users
    def create_user(self, user_id: str, email: str, password_hash: str) -> bool:
        try:
            with self.transaction() as conn:
                conn.execute(
                    "INSERT INTO users(id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                    (user_id, email, password_hash, iso()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self.read() as conn:
            return self._dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self.read() as conn:
            return self._dict(
                conn.execute("SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,)).fetchone()
            )

    def get_user_by_google_id(self, google_id: str) -> dict[str, Any] | None:
        with self.read() as conn:
            return self._dict(
                conn.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone()
            )

    def upsert_google_user(
        self,
        *,
        google_id: str,
        email: str,
    ) -> tuple[dict[str, Any], bool]:
        """Find or create a Google account.

        Registration is login: a new Google identity is inserted immediately.
        An existing password account with the same email is linked rather than
        duplicated.
        """
        now = utcnow()
        with self.transaction() as conn:
            by_google = conn.execute(
                "SELECT * FROM users WHERE google_id = ?", (google_id,)
            ).fetchone()
            by_email = conn.execute(
                "SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,)
            ).fetchone()
            created = False
            if by_google is not None:
                user = by_google
                # If the Google email changed, only update when no other
                # account already owns it.
                target_email = email if by_email is None or by_email["id"] == user["id"] else user["email"]
                conn.execute("UPDATE users SET email = ? WHERE id = ?", (target_email, user["id"]))
            elif by_email is not None:
                user = by_email
                conn.execute("UPDATE users SET google_id = ? WHERE id = ?", (google_id, user["id"]))
            else:
                user_id = uuid.uuid4().hex
                conn.execute(
                    """INSERT INTO users(id, email, password_hash, created_at, google_id)
                       VALUES (?, ?, '!google-oauth', ?, ?)""",
                    (user_id, email, iso(now), google_id),
                )
                created = True
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"] if not created else user_id,)).fetchone()
            return dict(row), created

    def link_google_user(
        self,
        *,
        user_id: str,
        google_id: str,
    ) -> dict[str, Any] | None:
        """Explicitly bind a Google identity to an already-authenticated user.

        Returns None when this google_id already belongs to another account, so
        the route can show a clean error instead of a unique-constraint 500.
        """
        with self.transaction() as conn:
            other = conn.execute(
                "SELECT id FROM users WHERE google_id = ? AND id <> ?",
                (google_id, user_id),
            ).fetchone()
            if other is not None:
                return None
            conn.execute("UPDATE users SET google_id = ? WHERE id = ?", (google_id, user_id))
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None


    def create_session(self, token_hash: str, user_id: str, days: int) -> None:
        now = utcnow()
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token_hash, user_id, iso(now), iso(now + timedelta(days=days))),
            )

    def session_user(self, token_hash: str) -> dict[str, Any] | None:
        now = iso()
        with self.read() as conn:
            row = conn.execute(
                """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
                   WHERE s.token_hash = ? AND s.expires_at > ?""",
                (token_hash, now),
            ).fetchone()
            return self._dict(row)

    def delete_session(self, token_hash: str) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def purge_sessions(self) -> int:
        with self.transaction() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (iso(),))
            return cur.rowcount

    # --------------------------------------------------------------- usage
    def usage_count(self, day: str, subject: str) -> int:
        with self.read() as conn:
            row = conn.execute(
                "SELECT count FROM usage WHERE day = ? AND subject = ?", (day, subject)
            ).fetchone()
            return int(row["count"]) if row else 0

    @staticmethod
    def _consume_usage(conn: sqlite3.Connection, day: str, subject: str, limit: int) -> None:
        row = conn.execute(
            "SELECT count FROM usage WHERE day = ? AND subject = ?", (day, subject)
        ).fetchone()
        used = int(row["count"]) if row else 0
        if used >= limit:
            raise QuotaExceeded(used=used, limit=limit)
        conn.execute(
            """INSERT INTO usage(day, subject, count) VALUES (?, ?, 1)
               ON CONFLICT(day, subject) DO UPDATE SET count = count + 1""",
            (day, subject),
        )

    @staticmethod
    def _refund_usage(conn: sqlite3.Connection, day: str, subject: str) -> None:
        conn.execute(
            "UPDATE usage SET count = count - 1 WHERE day = ? AND subject = ? AND count > 0",
            (day, subject),
        )
        conn.execute("DELETE FROM usage WHERE day = ? AND subject = ? AND count <= 0", (day, subject))

    # ---------------------------------------------------------------- jobs
    def create_job(
        self,
        *,
        job_id: str,
        user_id: str | None,
        anon_id: str,
        ip_hash: str,
        mode: str,
        label: str,
        input_path: str,
        gt_path: str | None,
        result_dir: str,
        usage_day: str,
        usage_subject: str,
        daily_limit: int,
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
                if user_id:
                    active = conn.execute(
                        """SELECT id FROM jobs WHERE user_id = ? AND status IN ('queued','running')
                           AND created_at >= ? LIMIT 1""",
                        (user_id, active_since),
                    ).fetchone()
                else:
                    active = conn.execute(
                        """SELECT id FROM jobs WHERE anon_id = ? AND status IN ('queued','running')
                           AND created_at >= ? LIMIT 1""",
                        (anon_id, active_since),
                    ).fetchone()
                if active:
                    raise ActiveJobExists(active_job=active["id"])

            self._consume_usage(conn, usage_day, usage_subject, daily_limit)

            conn.execute(
                """INSERT INTO jobs(
                       id, user_id, anon_id, ip_hash, mode, label, input_path, gt_path,
                       result_dir, status, usage_day, usage_subject, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)""",
                (
                    job_id, user_id, None if user_id else anon_id, ip_hash, mode, label,
                    input_path, gt_path, result_dir, usage_day, usage_subject, now,
                ),
            )
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(row)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.read() as conn:
            return self._dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())

    def list_jobs(self, *, user_id: str | None, anon_id: str | None, limit: int = 20) -> list[dict[str, Any]]:
        with self.read() as conn:
            if user_id:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
            elif anon_id:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE anon_id = ? AND user_id IS NULL ORDER BY created_at DESC LIMIT ?",
                    (anon_id, limit),
                ).fetchall()
            else:
                rows = []
            return [dict(row) for row in rows]

    def active_jobs(self, *, user_id: str | None, anon_id: str | None, since: str) -> int:
        with self.read() as conn:
            if user_id:
                row = conn.execute(
                    """SELECT COUNT(*) AS n FROM jobs WHERE user_id = ? AND status IN ('queued','running')
                       AND created_at >= ?""",
                    (user_id, since),
                ).fetchone()
            elif anon_id:
                row = conn.execute(
                    """SELECT COUNT(*) AS n FROM jobs WHERE anon_id = ? AND user_id IS NULL
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

    def fail_job(self, job_id: str, error: str, *, refund: bool = True) -> None:
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return
            if row["status"] in {"done", "error"}:
                return
            refunded = int(row["refunded"])
            if refund and not refunded and row["usage_subject"]:
                self._refund_usage(conn, row["usage_day"], row["usage_subject"])
                refunded = 1
            conn.execute(
                """UPDATE jobs SET status = 'error', finished_at = ?, heartbeat_at = NULL,
                       error = ?, refunded = ? WHERE id = ?""",
                (iso(), error[:8000], refunded, job_id),
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
        self.fail_job(job_id, message, refund=True)

    def jobs_to_cleanup(self, cutoff: str) -> list[dict[str, Any]]:
        with self.read() as conn:
            rows = conn.execute(
                """SELECT id, result_dir, input_path FROM jobs
                   WHERE status IN ('done','error') AND finished_at IS NOT NULL
                     AND finished_at < ? AND files_deleted = 0""",
                (cutoff,),
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_files_deleted(self, job_id: str) -> None:
        with self.transaction() as conn:
            conn.execute("UPDATE jobs SET files_deleted = 1 WHERE id = ?", (job_id,))

    def claim_anon_jobs(self, user_id: str, anon_id: str) -> int:
        with self.transaction() as conn:
            cur = conn.execute(
                "UPDATE jobs SET user_id = ?, anon_id = NULL WHERE anon_id = ? AND user_id IS NULL",
                (user_id, anon_id),
            )
            return cur.rowcount

    def purge_usage_before(self, day: str) -> int:
        with self.transaction() as conn:
            cur = conn.execute("DELETE FROM usage WHERE day < ?", (day,))
            return cur.rowcount

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
            users = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        state = self.get_state("worker")
        return {
            "db": "ok",
            "users": int(users),
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
