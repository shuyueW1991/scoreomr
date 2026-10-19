"""FastAPI dependencies shared by route modules."""
from __future__ import annotations

from fastapi import Depends, Request, Response

from .auth import Actor, actor_from, client_ip
from .context import AppContext, get_ctx
from .errors import RateLimited, Unauthorized
from .ratelimit import SlidingWindow


def get_context(request: Request) -> AppContext:
    return get_ctx(request)


def get_actor(
    request: Request,
    response: Response,
    ctx: AppContext = Depends(get_context),
) -> Actor:
    return actor_from(request, response, ctx.db, ctx.settings, ctx.secret)


def require_user(actor: Actor = Depends(get_actor)) -> Actor:
    if actor.user is None:
        raise Unauthorized()
    return actor


def enforce_limit(
    request: Request,
    ctx: AppContext,
    limiter: SlidingWindow,
    scope: str,
    message: str = "操作过于频繁，请稍后再试",
) -> None:
    ip = client_ip(request, ctx.settings)
    allowed, retry = limiter.hit(f"{scope}:{ip}")
    if not allowed:
        raise RateLimited(message, retry_after=retry)
