"""Health, public configuration and current-session endpoints."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends

from .. import __version__
from ..auth import Actor, me_payload, refresh_actor
from ..context import AppContext
from ..deps import get_actor, get_context
from ..timeutil import iso, parse, utcnow

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(ctx: AppContext = Depends(get_context)) -> dict:
    db_health = ctx.db.health()
    worker = db_health.get("worker") or {}
    last = parse(worker.get("updated_at")) if isinstance(worker, dict) else None
    online = bool(last and utcnow() - last < timedelta(seconds=90))
    queue = db_health["queue"]
    return {
        "ok": True,
        "version": __version__,
        "db": db_health["db"],
        "queue": {"queued": queue["queued"], "running": queue["running"]},
        "worker": {
            "online": online,
            "last_seen": worker.get("updated_at") if isinstance(worker, dict) else None,
            "engines": worker.get("engines") if isinstance(worker, dict) else None,
            "mock": worker.get("mock") if isinstance(worker, dict) else None,
        },
        "server_time": iso(),
    }


@router.get("/config")
def public_config(ctx: AppContext = Depends(get_context)) -> dict:
    return {
        **ctx.settings.public_config,
        "samples": len(ctx.samples),
        "server_time": iso(),
    }


@router.get("/me")
def me(actor: Actor = Depends(get_actor), ctx: AppContext = Depends(get_context)) -> dict:
    refreshed = refresh_actor(actor, actor.user, ctx.db)
    payload = me_payload(refreshed, ctx.settings)
    payload["server_time"] = iso()
    return payload
