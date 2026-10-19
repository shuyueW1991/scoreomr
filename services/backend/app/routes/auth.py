"""Registration, password login, logout and Google OAuth login."""
from __future__ import annotations

import hmac
import logging
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from ..auth import (
    ANON_COOKIE,
    Actor,
    clear_session_cookie,
    client_ip,
    me_payload,
    session_user,
    set_session_cookie,
)
from ..context import AppContext
from ..deps import enforce_limit, get_context
from ..errors import Conflict, Unauthorized, ValidationFailed
from ..google_auth import OAuthError
from ..security import (
    hash_ip,
    hash_password,
    new_token,
    normalize_email,
    safe_next,
    token_digest,
    valid_email,
    verify_password,
)
from ..timeutil import day_key, utcnow

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

GOOGLE_STATE_COOKIE = "omr_oauth_state"
GOOGLE_NEXT_COOKIE = "omr_oauth_next"
OAUTH_COOKIE_MAX_AGE = 600


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)


def _actor_for_user(request: Request, ctx: AppContext, user: dict) -> Actor:
    now = utcnow()
    ip = client_ip(request, ctx.settings)
    ip_hash = hash_ip(ctx.secret, ip)
    anon = request.cookies.get(ANON_COOKIE)
    if not anon:
        anon = new_token(18)
        request.state.anon_id = anon
    day = day_key(now, ctx.settings.tz)
    subject = f"user:{user['id']}"
    used = ctx.db.usage_count(day, subject)
    return Actor(
        user=user,
        anon_id=anon,
        ip_hash=ip_hash,
        day=day,
        usage_subject=subject,
        used_today=used,
    )


def _issue_session(response: Response, request: Request, ctx: AppContext, user: dict) -> Response:
    token = new_token(32)
    ctx.db.create_session(token_digest(token), user["id"], ctx.settings.session_days)
    set_session_cookie(response, token, ctx.settings)
    anon = request.cookies.get(ANON_COOKIE)
    if anon:
        ctx.db.claim_anon_jobs(user["id"], anon)
    return response


def _clear_oauth_cookies(response: Response, ctx: AppContext) -> None:
    for name in (GOOGLE_STATE_COOKIE, GOOGLE_NEXT_COOKIE):
        response.delete_cookie(
            name,
            path="/",
            httponly=True,
            samesite="lax",
            secure=ctx.settings.secure_cookies,
        )


def _oauth_failure(code: str, ctx: AppContext, *, account: bool = False) -> RedirectResponse:
    suffix = f"/account?google_error={quote(code)}" if account else f"/login?error={quote(code)}"
    response = RedirectResponse(suffix, status_code=302)
    _clear_oauth_cookies(response, ctx)
    return response


@router.get("/google/start")
def google_start(
    request: Request,
    next: str = "/account",
    ctx: AppContext = Depends(get_context),
) -> RedirectResponse:
    current = session_user(request, ctx.db, ctx.settings)
    if not ctx.google.enabled:
        return _oauth_failure("google_not_configured", ctx, account=current is not None)
    state = new_token(24)
    target = safe_next(next)
    try:
        location = ctx.google.authorize_url(state)
    except OAuthError as exc:
        log.warning("google authorize failed: %s", exc)
        return _oauth_failure("google_failed", ctx, account=current is not None)
    response = RedirectResponse(location, status_code=302)
    for name, value in ((GOOGLE_STATE_COOKIE, state), (GOOGLE_NEXT_COOKIE, target)):
        response.set_cookie(
            name,
            value,
            max_age=OAUTH_COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=ctx.settings.secure_cookies,
            path="/",
        )
    return response


@router.get("/google/callback")
def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    ctx: AppContext = Depends(get_context),
) -> RedirectResponse:
    current = session_user(request, ctx.db, ctx.settings)

    def fail(code: str) -> RedirectResponse:
        return _oauth_failure(code, ctx, account=current is not None)

    if error:
        return fail("google_denied")
    cookie_state = request.cookies.get(GOOGLE_STATE_COOKIE)
    if not code or not state or not cookie_state or not hmac.compare_digest(cookie_state, state):
        return fail("google_state")
    target = safe_next(request.cookies.get(GOOGLE_NEXT_COOKIE))
    try:
        access_token = ctx.google.exchange_code(code)
        info = ctx.google.userinfo(access_token)
    except OAuthError as exc:
        log.warning("google oauth failed: %s", exc)
        return fail("google_exchange_failed")
    except Exception:  # noqa: BLE001
        log.exception("unexpected Google OAuth failure")
        return fail("google_failed")

    email = normalize_email(str(info.get("email") or ""))
    verified = info.get("email_verified") in (True, 1, "true", "True")
    google_id = str(info.get("sub") or info.get("id") or "")
    if not email or not valid_email(email) or not verified or not google_id:
        return fail("google_email_unverified")
    if current is not None:
        # Explicit binding: the user is already signed in. Only allow a Google
        # identity with the same verified email, never a silent account merge.
        if normalize_email(current["email"]) != email:
            return fail("google_email_mismatch")
        linked = ctx.db.link_google_user(
            user_id=current["id"],
            google_id=google_id,
        )
        if linked is None:
            return fail("google_already_linked")
        user, created = linked, False
    else:
        # A password account with the same email is NOT auto-merged. Password
        # registration does not verify email ownership, so auto-merging would
        # let someone pre-register a victim's email. Sign in with the
        # password and bind Google explicitly.
        existing = ctx.db.get_user_by_email(email)
        if existing is not None and existing.get("google_id") not in (None, google_id):
            # Never silently replace an existing Google binding from a fresh
            # login. The signed-in owner can rebind explicitly from /account.
            return fail("google_already_linked")
        if (
            existing is not None
            and not existing.get("google_id")
            and existing.get("password_hash") != "!google-oauth"
        ):
            return fail("google_account_exists")
        user, created = ctx.db.upsert_google_user(
            google_id=google_id,
            email=email,
        )
    log.info("google login user=%s created=%s", user["id"], created)
    response = RedirectResponse(target, status_code=302)
    _issue_session(response, request, ctx, user)
    _clear_oauth_cookies(response, ctx)
    return response


@router.post("/register", status_code=201)
def register(payload: Credentials, request: Request, ctx: AppContext = Depends(get_context)) -> JSONResponse:
    enforce_limit(request, ctx, ctx.register_limiter, "register", "注册尝试过于频繁")
    email = normalize_email(payload.email)
    if not valid_email(email):
        raise ValidationFailed("邮箱格式不正确")
    if len(payload.password) < 8:
        raise ValidationFailed("密码至少 8 位")
    user_id = uuid.uuid4().hex
    if not ctx.db.create_user(user_id, email, hash_password(payload.password)):
        raise Conflict("这个邮箱已经注册")
    user = ctx.db.get_user(user_id)
    if user is None:  # pragma: no cover
        raise ValidationFailed("注册失败")
    actor = _actor_for_user(request, ctx, user)
    response = JSONResponse(me_payload(actor, ctx.settings), status_code=201)
    return _issue_session(response, request, ctx, user)


@router.post("/login")
def login(payload: Credentials, request: Request, ctx: AppContext = Depends(get_context)) -> JSONResponse:
    enforce_limit(request, ctx, ctx.login_limiter, "login", "登录尝试过于频繁")
    email = normalize_email(payload.email)
    user = ctx.db.get_user_by_email(email) if valid_email(email) else None
    # Verify against a dummy hash for unknown accounts so timing does not
    # reveal whether an email exists.
    stored = user.get("password_hash") if user else None
    if not verify_password(payload.password, stored):
        raise Unauthorized("邮箱或密码不正确")
    actor = _actor_for_user(request, ctx, user)
    response = JSONResponse(me_payload(actor, ctx.settings))
    return _issue_session(response, request, ctx, user)


@router.post("/logout")
def logout(request: Request, ctx: AppContext = Depends(get_context)) -> JSONResponse:
    from ..auth import SESSION_COOKIE

    token = request.cookies.get(SESSION_COOKIE)
    if token:
        ctx.db.delete_session(token_digest(token))
    response = JSONResponse({"ok": True})
    clear_session_cookie(response, ctx.settings)
    return response
