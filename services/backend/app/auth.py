"""Request actors: optional user session, anonymous cookie, quotas."""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi import Request, Response

from .config import Settings
from .db import Database
from .security import client_ip_from_headers, hash_ip
from .timeutil import day_key, iso, next_reset, utcnow

SESSION_COOKIE = "omr_session"
ANON_COOKIE = "omr_anon"
ANON_MAX_AGE = 180 * 24 * 3600
ANON_RE = re.compile(r"^[A-Za-z0-9_-]{20,80}$")


@dataclass
class Actor:
    user: dict[str, Any] | None
    anon_id: str
    ip_hash: str
    day: str
    usage_subject: str
    used_today: int

    @property
    def user_id(self) -> str | None:
        return self.user["id"] if self.user else None

    @property
    def owner_filter(self) -> dict[str, str | None]:
        return {"user_id": self.user_id, "anon_id": None if self.user else self.anon_id}


def client_ip(request: Request, settings: Settings) -> str:
    peer = request.client.host if request.client else "unknown"
    return client_ip_from_headers(
        peer,
        request.headers.getlist("x-forwarded-for"),
        settings.trust_proxy,
    )


def session_user(request: Request, db: Database, settings: Settings) -> dict[str, Any] | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token or len(token) < 20:
        return None
    from .security import token_digest

    return db.session_user(token_digest(token))


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
        secure=settings.secure_cookies,
        path="/",
    )
    return value


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=settings.secure_cookies
    )


def actor_from(
    request: Request,
    response: Response,
    db: Database,
    settings: Settings,
    secret: str,
) -> Actor:
    now = utcnow()
    user = session_user(request, db, settings)
    anon_id = ensure_anon_id(request, response, settings)
    ip = client_ip(request, settings)
    ip_hash = hash_ip(secret, ip)
    subject = f"user:{user['id']}" if user else f"ip:{ip_hash}"
    day = day_key(now, settings.tz)
    used = db.usage_count(day, subject)
    return Actor(
        user=user,
        anon_id=anon_id,
        ip_hash=ip_hash,
        day=day,
        usage_subject=subject,
        used_today=used,
    )


def quota_payload(actor: Actor, settings: Settings) -> dict[str, Any]:
    now = utcnow()
    limit = settings.daily_limit
    return {
        "daily_limit": limit,
        "used_today": actor.used_today,
        "remaining_today": max(0, limit - actor.used_today),
        "resets_at": iso(next_reset(now, settings.tz)),
        "timezone": settings.timezone,
    }


def user_payload(user: dict[str, Any] | None, settings: Settings) -> dict[str, Any] | None:
    if not user:
        return None
    return {
        "id": user["id"],
        "email": user["email"],
        "google_linked": bool(user.get("google_id")),
        "created_at": user["created_at"],
    }


def me_payload(actor: Actor, settings: Settings) -> dict[str, Any]:
    return {
        "user": user_payload(actor.user, settings),
        "quota": quota_payload(actor, settings),
    }


def refresh_actor(actor: Actor, user: dict[str, Any] | None, db: Database) -> Actor:
    used = db.usage_count(actor.day, actor.usage_subject)
    return Actor(
        user=user,
        anon_id=actor.anon_id,
        ip_hash=actor.ip_hash,
        day=actor.day,
        usage_subject=actor.usage_subject,
        used_today=used,
    )


def active_since(settings: Settings, now=None) -> str:
    now = now or utcnow()
    return iso(now - timedelta(seconds=max(600, settings.job_timeout_seconds * 2)))
