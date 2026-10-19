"""Environment-backed configuration.

The service intentionally has no pydantic-settings dependency: the whole
surface is a handful of typed environment variables, validated once at boot.
"""
from __future__ import annotations

import os
import secrets
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:  # Linux/macOS; the deployment targets one of them.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

ENGINE_NAMES = ("audiveris", "homr", "oemer")


class ConfigError(RuntimeError):
    """Raised when the deployment configuration is unsafe or malformed."""


def _env(env: Mapping[str, str], key: str, default: str = "") -> str:
    value = env.get(key)
    return default if value is None else str(value).strip()


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = _env(env, key)
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc


def _float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = _env(env, key)
    if raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from exc


def _csv(env: Mapping[str, str], key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = _env(env, key)
    if raw == "":
        return default
    items = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
    return items or default


@dataclass(frozen=True)
class Settings:
    app_name: str = "ScoreOMR"
    app_env: str = "production"
    app_url: str = "http://localhost:8080"
    timezone: str = "Asia/Shanghai"
    data_dir: Path = Path("data")
    database_path: Path = Path("data/scoreomr.db")
    session_secret: str = ""
    session_cookie_secure: bool = False
    session_days: int = 30
    daily_limit: int = 1
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""
    max_upload_mb: int = 20
    max_gt_mb: int = 2
    max_queue_length: int = 20
    max_active_jobs: int = 1
    job_retention_days: int = 7
    job_timeout_seconds: int = 900
    omr_mock: bool = False
    omr_engines: tuple[str, ...] = ("audiveris", "homr")
    audiveris_bin: str = ""
    homr_bin: str = ""
    worker_poll_seconds: float = 1.5
    trust_proxy: bool = True
    registration_per_hour: int = 10
    uploads_per_10min: int = 8
    logins_per_10min: int = 20
    samples_dir: Path = field(default=Path("samples"), compare=False)
    tz: ZoneInfo = field(default_factory=lambda: ZoneInfo("Asia/Shanghai"), compare=False)

    # ------------------------------------------------------------------ load
    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        app_env = _env(env, "APP_ENV", "production").lower()
        data_dir = Path(_env(env, "DATA_DIR", "data")).expanduser()
        database = Path(_env(env, "DATABASE_PATH", str(data_dir / "scoreomr.db"))).expanduser()
        app_url = _env(env, "APP_URL", "http://localhost:8080").rstrip("/")
        google_redirect_uri = _env(env, "GOOGLE_REDIRECT_URI") or f"{app_url}/api/auth/google/callback"
        secure_raw = _env(env, "SESSION_COOKIE_SECURE")
        secure = _bool(env, "SESSION_COOKIE_SECURE", app_url.startswith("https://")) if secure_raw else app_url.startswith("https://")
        tz_name = _env(env, "APP_TIMEZONE", "Asia/Shanghai")
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError as exc:
            raise ConfigError(f"unknown APP_TIMEZONE: {tz_name}") from exc

        settings = cls(
            app_name=_env(env, "APP_NAME", "ScoreOMR"),
            app_env=app_env,
            app_url=app_url,
            timezone=tz_name,
            data_dir=data_dir,
            database_path=database,
            session_secret=_env(env, "SESSION_SECRET"),
            session_cookie_secure=secure,
            session_days=_int(env, "SESSION_DAYS", 30),
            daily_limit=_int(env, "DAILY_LIMIT", 1),
            google_client_id=_env(env, "GOOGLE_CLIENT_ID"),
            google_client_secret=_env(env, "GOOGLE_CLIENT_SECRET"),
            google_redirect_uri=google_redirect_uri,
            max_upload_mb=_int(env, "MAX_UPLOAD_MB", 20),
            max_gt_mb=_int(env, "MAX_GT_MB", 2),
            max_queue_length=_int(env, "MAX_QUEUE_LENGTH", 20),
            max_active_jobs=_int(env, "MAX_ACTIVE_JOBS", 1),
            job_retention_days=_int(env, "JOB_RETENTION_DAYS", 7),
            job_timeout_seconds=_int(env, "JOB_TIMEOUT_SECONDS", 900),
            omr_mock=_bool(env, "OMR_MOCK", False),
            omr_engines=_csv(env, "OMR_ENGINES", ("audiveris", "homr")),
            audiveris_bin=_env(env, "AUDIVERIS_BIN"),
            homr_bin=_env(env, "HOMR_BIN"),
            worker_poll_seconds=_float(env, "WORKER_POLL_SECONDS", 1.5),
            trust_proxy=_bool(env, "TRUST_PROXY", True),
            registration_per_hour=_int(env, "REGISTRATION_PER_HOUR", 10),
            uploads_per_10min=_int(env, "UPLOADS_PER_10MIN", 8),
            logins_per_10min=_int(env, "LOGINS_PER_10MIN", 20),
            samples_dir=Path(_env(env, "SAMPLES_DIR", str(Path(__file__).resolve().parents[1] / "samples"))),
            tz=tz,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.app_env not in {"production", "development", "test"}:
            raise ConfigError("APP_ENV must be production, development or test")
        if self.app_env == "production" and self.omr_mock:
            raise ConfigError("OMR_MOCK=true is refused when APP_ENV=production")
        if not 0 <= self.daily_limit <= 100:
            raise ConfigError("DAILY_LIMIT must be between 0 and 100")
        if not self.google_redirect_uri.startswith(("http://", "https://")):
            raise ConfigError("GOOGLE_REDIRECT_URI must start with http:// or https://")
        if self.max_upload_mb <= 0 or self.max_gt_mb <= 0:
            raise ConfigError("MAX_UPLOAD_MB and MAX_GT_MB must be positive")
        if not self.omr_engines:
            raise ConfigError("OMR_ENGINES must not be empty")
        unknown = set(self.omr_engines) - set(ENGINE_NAMES)
        if unknown:
            raise ConfigError(f"unknown OMR_ENGINES: {', '.join(sorted(unknown))}")
        if not self.app_url.startswith(("http://", "https://")):
            raise ConfigError("APP_URL must start with http:// or https://")
        if self.worker_poll_seconds < 0.2:
            raise ConfigError("WORKER_POLL_SECONDS is too small")

    # --------------------------------------------------------------- helpers
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"

    @property
    def google_auth_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def secure_cookies(self) -> bool:
        return self.session_cookie_secure

    @property
    def scratch_dir(self) -> Path:
        return self.data_dir / "scratch"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def public_config(self) -> dict:
        return {
            "app_name": self.app_name,
            "app_env": self.app_env,
            "daily_limit": self.daily_limit,
            "google_auth_enabled": self.google_auth_enabled,
            "max_upload_mb": self.max_upload_mb,
            "job_retention_days": self.job_retention_days,
            "omr_mock": self.omr_mock,
            "engines": list(self.omr_engines),
        }

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.jobs_dir, self.uploads_dir, self.scratch_dir):
            path.mkdir(parents=True, exist_ok=True)

    def resolve_secret(self) -> str:
        """Return the cookie/session secret, creating one on first boot.

        Persisting the generated secret in the data volume means a moved or
        restarted deployment keeps users logged in without shipping a default
        secret in Git.
        """
        if self.session_secret:
            if len(self.session_secret) < 32:
                raise ConfigError("SESSION_SECRET must be at least 32 characters")
            return self.session_secret
        self.data_dir.mkdir(parents=True, exist_ok=True)
        secret_file = self.data_dir / "session_secret"
        lock_file = self.data_dir / "session_secret.lock"
        # API and worker may start at the same time on a fresh volume.  A lock
        # guarantees they agree on one secret instead of racing to replace it.
        lock_handle = None
        if fcntl:
            lock_handle = lock_file.open("a+")
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            if secret_file.exists():
                value = secret_file.read_text(encoding="utf-8").strip()
                if len(value) >= 32:
                    return value
            value = secrets.token_urlsafe(48)
            tmp = secret_file.with_suffix(".tmp")
            tmp.write_text(value + "\n", encoding="utf-8")
            tmp.chmod(stat.S_IRUSR | stat.S_IWUSR)
            tmp.replace(secret_file)
            return value
        finally:
            if lock_handle is not None:
                lock_handle.close()
