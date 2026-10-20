"""FastAPI dependencies shared by route modules."""
from __future__ import annotations

from fastapi import Depends, Request, Response

from .auth import Actor, ensure_anon_id
from .context import AppContext, get_ctx


def get_context(request: Request) -> AppContext:
    return get_ctx(request)


def get_actor(
    request: Request,
    response: Response,
    ctx: AppContext = Depends(get_context),
) -> Actor:
    anon_id = ensure_anon_id(request, response, ctx.settings)
    return Actor(anon_id=anon_id)