"""Anonymous browser identity for job ownership.

There is no account system: recognition history is scoped to a per-browser
cookie (omr_anon), so the same machine keeps seeing its own jobs while other
clients cannot read them.
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Request, Response

from .config import Settings
from .timeutil import iso, utcnow

ANON_COOKIE = "omr_anon"
ANON_MAX_AGE = 180 * 24 * 3600
ANON_RE = re.compile(r"^[A-Za-z0-9_-]{20,80}$")


@dataclass
class Actor:
    anon_id: str

    @property
    def owner_filter(self) -> dict[str, str | None]:
        return {"anon_id": self.anon_id}


def active_since_iso(job_timeout_seconds: int) -> str:
    """Cutoff for counting an anonymous user's active jobs."""
    now = utcnow()
    return iso(now - timedelta(seconds=max(600, job_timeout_seconds * 2)))


def _valid_anon(value: str | None) -> bool:
    return bool(value and ANON_RE.match(value))


def ensure_anon_id(request: Request, response: Response, settings: Settings) -> str:
    value = request.cookies.get(ANON_COOKIE)
    if _valid_anon(value):
        request.state.anon_id = value
        return value  # type: ignore[return-value]
    value = secrets.token_urlsafe(24)
    request.state.anon_id = value
    response.set_cookie(
        ANON_COOKIE,
        value,
        max_age=ANON_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.cookies_secure,
        path="/",
    )
    return value