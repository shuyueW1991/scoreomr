"""Minimal Google OAuth 2.0 (authorization-code) client.

No Auth.js/NextAuth is involved: the browser is redirected to Google, the
callback exchanges the code server-side, and the resulting user is linked to
the local account by google_id + verified email.  A state cookie protects the
callback from CSRF.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from .config import Settings


class OAuthError(RuntimeError):
    """A user-facing OAuth failure; never contains tokens or secrets."""


class GoogleOAuth:
    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        self.settings = settings
        self.http = http or httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))

    @property
    def enabled(self) -> bool:
        return self.settings.google_auth_enabled

    def authorize_url(self, state: str) -> str:
        if not self.enabled:
            raise OAuthError("Google 登录未配置")
        query = urlencode(
            {
                "client_id": self.settings.google_client_id,
                "redirect_uri": self.settings.google_redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "access_type": "online",
                "include_granted_scopes": "true",
                "prompt": "select_account",
            }
        )
        return f"{self.AUTH_URL}?{query}"

    def exchange_code(self, code: str) -> str:
        if not self.enabled:
            raise OAuthError("Google 登录未配置")
        try:
            response = self.http.post(
                self.TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self.settings.google_client_id,
                    "client_secret": self.settings.google_client_secret,
                    "redirect_uri": self.settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        except httpx.HTTPError as exc:
            raise OAuthError("连接 Google 失败，请稍后重试") from exc
        if response.status_code >= 400:
            raise OAuthError("Google 授权码校验失败")
        try:
            body = response.json()
        except ValueError as exc:
            raise OAuthError("Google 返回了无效响应") from exc
        access_token = body.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise OAuthError("Google 未返回 access_token")
        return access_token

    def userinfo(self, access_token: str) -> dict[str, Any]:
        try:
            response = self.http.get(
                self.USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.HTTPError as exc:
            raise OAuthError("读取 Google 用户信息失败") from exc
        if response.status_code >= 400:
            raise OAuthError("Google 用户信息校验失败")
        try:
            body = response.json()
        except ValueError as exc:
            raise OAuthError("Google 用户信息格式错误") from exc
        if not isinstance(body, dict):
            raise OAuthError("Google 用户信息格式错误")
        return body

    def close(self) -> None:
        self.http.close()
