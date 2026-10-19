from __future__ import annotations

from datetime import datetime

import pytest

from app.config import ConfigError, Settings
from tests.conftest import make_settings


def test_health_and_public_config(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    body = health.json()
    assert body["ok"] is True
    assert body["db"] == "ok"
    assert body["queue"] == {"queued": 0, "running": 0}
    assert body["worker"]["online"] is False

    config = client.get("/api/config").json()
    assert config["daily_limit"] == 1
    assert config["samples"] == 9
    assert config["omr_mock"] is True
    assert config["google_auth_enabled"] is False


def test_me_creates_anonymous_cookie(client):
    response = client.get("/api/me")
    assert response.status_code == 200
    cookie = response.headers.get("set-cookie", "")
    assert "omr_anon=" in cookie
    assert "HttpOnly" in cookie
    body = response.json()
    assert body["user"] is None
    assert body["quota"]["daily_limit"] == 1
    assert body["quota"]["remaining_today"] == 1
    reset = datetime.fromisoformat(body["quota"]["resets_at"].replace("Z", "+00:00"))
    assert reset > datetime.now(reset.tzinfo)


def test_quota_resets_at_is_next_local_midnight(client):
    quota = client.get("/api/me").json()["quota"]
    reset = datetime.fromisoformat(quota["resets_at"].replace("Z", "+00:00"))
    local = reset.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Shanghai"))
    assert (local.hour, local.minute, local.second) == (0, 0, 0)


def test_production_refuses_mock_omr(tmp_path):
    with pytest.raises(ConfigError):
        Settings.from_env(
            {
                "APP_ENV": "production",
                "DATA_DIR": str(tmp_path),
                "OMR_MOCK": "true",
            }
        )


def test_secure_cookie_derived_from_https_url(tmp_path):
    settings = make_settings(tmp_path, APP_URL="https://omr.example.com", SESSION_COOKIE_SECURE="")
    assert settings.secure_cookies is True


def test_environment_defaults_are_portable(tmp_path):
    settings = Settings.from_env(
        {
            "APP_ENV": "development",
            "DATA_DIR": str(tmp_path),
            "OMR_MOCK": "true",
        }
    )
    assert settings.omr_engines == ("audiveris", "homr")
    assert settings.data_dir == tmp_path
    assert settings.database_path == tmp_path / "scoreomr.db"
