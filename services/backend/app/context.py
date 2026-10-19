"""Composition root shared by the API process and tests."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Request

from .config import Settings
from .db import Database
from .google_auth import GoogleOAuth
from .ratelimit import SlidingWindow
from .timeutil import utcnow

log = logging.getLogger(__name__)


@dataclass
class AppContext:
    settings: Settings
    secret: str
    db: Database
    google: GoogleOAuth
    samples: list[dict[str, Any]] = field(default_factory=list)
    started_at: datetime = field(default_factory=utcnow)
    register_limiter: SlidingWindow = field(init=False)
    login_limiter: SlidingWindow = field(init=False)
    upload_limiter: SlidingWindow = field(init=False)

    def __post_init__(self) -> None:
        s = self.settings
        self.register_limiter = SlidingWindow(s.registration_per_hour, 3600)
        self.login_limiter = SlidingWindow(s.logins_per_10min, 600)
        self.upload_limiter = SlidingWindow(s.uploads_per_10min, 600)

    @classmethod
    def build(
        cls,
        settings: Settings | None = None,
        *,
        google: GoogleOAuth | None = None,
        load_samples: bool = True,
    ) -> "AppContext":
        settings = settings or Settings.from_env()
        settings.ensure_dirs()
        secret = settings.resolve_secret()
        db = Database(settings.database_path)
        db.init()
        ctx = cls(
            settings=settings,
            secret=secret,
            db=db,
            google=google or GoogleOAuth(settings),
        )
        if load_samples:
            ctx.samples = load_sample_manifest(settings.samples_dir)
        return ctx

    def sample(self, sample_id: str) -> dict[str, Any] | None:
        return next((s for s in self.samples if s["id"] == sample_id), None)


def load_sample_manifest(samples_dir: str | Path) -> list[dict[str, Any]]:
    samples_dir = Path(samples_dir).resolve()
    manifest = samples_dir / "manifest.json"
    if not manifest.exists():
        log.warning("sample manifest not found at %s", manifest)
        return []
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("cannot read sample manifest: %s", exc)
        return []

    out: list[dict[str, Any]] = []
    for item in raw:
        image = (samples_dir / item["image"]).resolve()
        gt = (samples_dir / item["gt"]).resolve() if item.get("gt") else None
        if not image.is_relative_to(samples_dir) or not image.exists():
            log.warning("sample image missing: %s", image)
            continue
        if gt is not None and (not gt.is_relative_to(samples_dir) or not gt.exists()):
            log.warning("sample ground truth missing: %s", gt)
            gt = None
        out.append(
            {
                "id": item["id"],
                "name": item["name"],
                "category": item.get("category", "sample"),
                "category_label": item.get("category_label", item.get("category", "sample")),
                "blurb": item.get("blurb", ""),
                "gt_notes": item.get("gt_notes"),
                "image_path": image,
                "gt_path": gt,
            }
        )
    return out


def public_sample(sample: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": sample["id"],
        "name": sample["name"],
        "category": sample["category"],
        "category_label": sample["category_label"],
        "blurb": sample["blurb"],
        "gt_notes": sample["gt_notes"],
        "image_url": f"/api/samples/{sample['id']}/image",
    }


def get_ctx(request: Request) -> AppContext:
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:  # pragma: no cover - programming error
        raise RuntimeError("application context is not initialised")
    return ctx
