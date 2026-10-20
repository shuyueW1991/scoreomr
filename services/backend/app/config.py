"""Environment-backed configuration.

The service intentionally has no pydantic-settings dependency: the whole
surface is a handful of typed environment variables, validated once at boot.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    max_upload_mb: int = 20
    max_gt_mb: int = 2
    max_queue_length: int = 20
    max_active_jobs: int = 1
    job_timeout_seconds: int = 900
    omr_mock: bool = False
    omr_engines: tuple[str, ...] = ("audiveris", "homr")
    audiveris_bin: str = ""
    homr_bin: str = ""
    worker_poll_seconds: float = 1.5
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
            max_upload_mb=_int(env, "MAX_UPLOAD_MB", 20),
            max_gt_mb=_int(env, "MAX_GT_MB", 2),
            max_queue_length=_int(env, "MAX_QUEUE_LENGTH", 20),
            max_active_jobs=_int(env, "MAX_ACTIVE_JOBS", 1),
            job_timeout_seconds=_int(env, "JOB_TIMEOUT_SECONDS", 900),
            omr_mock=_bool(env, "OMR_MOCK", False),
            omr_engines=_csv(env, "OMR_ENGINES", ("audiveris", "homr")),
            audiveris_bin=_env(env, "AUDIVERIS_BIN"),
            homr_bin=_env(env, "HOMR_BIN"),
            worker_poll_seconds=_float(env, "WORKER_POLL_SECONDS", 1.5),
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
    def cookies_secure(self) -> bool:
        return self.app_url.startswith("https://")

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
            "max_upload_mb": self.max_upload_mb,
            "omr_mock": self.omr_mock,
            "engines": list(self.omr_engines),
        }

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.jobs_dir, self.uploads_dir, self.scratch_dir):
            path.mkdir(parents=True, exist_ok=True)