from __future__ import annotations

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
    assert config["samples"] == 9
    assert config["omr_mock"] is True
    assert config["max_upload_mb"] == 20
    assert config["engines"] == ["audiveris", "homr"]


def test_cookies_secure_derived_from_https_url(tmp_path):
    settings = make_settings(tmp_path, APP_URL="https://omr.example.com")
    assert settings.cookies_secure is True
    settings = make_settings(tmp_path, APP_URL="http://localhost:8080")
    assert settings.cookies_secure is False


def test_production_refuses_mock_omr(tmp_path):
    with pytest.raises(ConfigError):
        Settings.from_env(
            {
                "APP_ENV": "production",
                "DATA_DIR": str(tmp_path),
                "OMR_MOCK": "true",
            }
        )


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