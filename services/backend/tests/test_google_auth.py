from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings, register


def google_app(tmp_path):
    settings = make_settings(
        tmp_path,
        GOOGLE_CLIENT_ID="client-id.apps.googleusercontent.com",
        GOOGLE_CLIENT_SECRET="client-secret",
        GOOGLE_REDIRECT_URI="http://testserver/api/auth/google/callback",
    )
    return create_app(settings)


def patch_google(ctx, email: str = "google@example.com", sub: str = "google-sub-1") -> None:
    ctx.google.exchange_code = lambda code: "access-token"  # type: ignore[method-assign]
    ctx.google.userinfo = lambda token: {  # type: ignore[method-assign]
        "sub": sub,
        "email": email,
        "email_verified": True,
        "name": "Google User",
        "picture": "https://example.com/avatar.png",
    }


def start_google(client: TestClient, next_path: str = "/account") -> str:
    response = client.get(
        f"/api/auth/google/start?next={next_path}", follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"].startswith("https://accounts.google.com/")
    state = client.cookies.get("omr_oauth_state")
    assert state
    return state


def test_google_start_redirects_with_state_and_next(tmp_path):
    app = google_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/auth/google/start?next=/account", follow_redirects=False)
        assert response.status_code == 302
        location = response.headers["location"]
        assert "client_id=client-id.apps.googleusercontent.com" in location
        assert "redirect_uri=http%3A%2F%2Ftestserver%2Fapi%2Fauth%2Fgoogle%2Fcallback" in location
        assert "scope=openid+email+profile" in location
        assert client.cookies.get("omr_oauth_state")
        assert str(client.cookies.get("omr_oauth_next")).strip('"') == "/account"


def test_google_callback_creates_free_user(tmp_path):
    app = google_app(tmp_path)
    with TestClient(app) as client:
        patch_google(app.state.ctx)
        state = start_google(client)
        response = client.get(
            f"/api/auth/google/callback?code=abc&state={state}",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/account"
        me = client.get("/api/me").json()
        assert me["user"]["email"] == "google@example.com"
        assert me["user"]["google_linked"] is True
        assert me["quota"]["daily_limit"] == 1
        assert me["quota"]["remaining_today"] == 1
        user = app.state.ctx.db.get_user_by_email("google@example.com")
        assert user and user["google_id"] == "google-sub-1"
        assert not client.cookies.get("omr_oauth_state")


def test_google_binds_existing_email_when_logged_in(tmp_path):
    app = google_app(tmp_path)
    with TestClient(app) as client:
        register(client, email="linked@example.com")
        patch_google(app.state.ctx, email="linked@example.com", sub="google-sub-2")
        state = start_google(client, "/account")
        response = client.get(
            f"/api/auth/google/callback?code=abc&state={state}",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/account"
        me = client.get("/api/me").json()
        assert me["user"]["google_linked"] is True
        user = app.state.ctx.db.get_user_by_email("linked@example.com")
        assert user and user["google_id"] == "google-sub-2"

        # Once bound, a fresh Google login (without a password session) works.
        client.post("/api/auth/logout")
        state = start_google(client, "/account")
        client.get(
            f"/api/auth/google/callback?code=abc&state={state}",
            follow_redirects=False,
        )
        assert client.get("/api/me").json()["user"]["email"] == "linked@example.com"


def test_google_refuses_auto_merge_of_password_account(tmp_path):
    app = google_app(tmp_path)
    with TestClient(app) as client:
        register(client, email="password-only@example.com")
        client.post("/api/auth/logout")
        patch_google(app.state.ctx, email="password-only@example.com", sub="google-sub-5")
        state = start_google(client, "/account")
        response = client.get(
            f"/api/auth/google/callback?code=abc&state={state}",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"].startswith("/login?error=google_account_exists")
        user = app.state.ctx.db.get_user_by_email("password-only@example.com")
        assert user and user["google_id"] is None


def test_google_bind_rejects_different_email(tmp_path):
    app = google_app(tmp_path)
    with TestClient(app) as client:
        register(client, email="owner@example.com")
        patch_google(app.state.ctx, email="someone-else@example.com", sub="google-sub-6")
        state = start_google(client, "/account")
        response = client.get(
            f"/api/auth/google/callback?code=abc&state={state}",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"].startswith("/account?google_error=google_email_mismatch")
        user = app.state.ctx.db.get_user_by_email("owner@example.com")
        assert user and user["google_id"] is None


def test_google_callback_rejects_bad_state(tmp_path):
    app = google_app(tmp_path)
    with TestClient(app) as client:
        patch_google(app.state.ctx)
        response = client.get(
            "/api/auth/google/callback?code=abc&state=wrong", follow_redirects=False
        )
        assert response.status_code == 302
        assert response.headers["location"].startswith("/login?error=google_state")


def test_google_not_configured_redirects_to_login(tmp_path):
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/auth/google/start", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"].startswith("/login?error=google_not_configured")
        assert client.get("/api/config").json()["google_auth_enabled"] is False
