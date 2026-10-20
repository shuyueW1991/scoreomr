"""Health and public configuration endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import __version__
from ..context import AppContext
from ..deps import get_context
from ..timeutil import iso, parse, utcnow
from datetime import timedelta

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