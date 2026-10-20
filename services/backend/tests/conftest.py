from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.main import create_app
from app.timeutil import iso


BACKEND = Path(__file__).resolve().parents[1]
SAMPLES = BACKEND / "samples"


def make_settings(tmp_path: Path, **overrides: str) -> Settings:
    env = {
        "APP_ENV": "test",
        "DATA_DIR": str(tmp_path / "data"),
        "APP_URL": "http://testserver",
        "OMR_MOCK": "true",
        "SAMPLES_DIR": str(SAMPLES),
        "LOG_LEVEL": "WARNING",
    }
    env.update(overrides)
    return Settings.from_env(env)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def create_sample_job(client: TestClient, sample_id: str = "clean_piano", mode: str = "compare") -> dict[str, Any]:
    response = client.post(f"/api/samples/{sample_id}/run", json={"mode": mode})
    assert response.status_code == 201, response.text
    return response.json()["job"]


def finish_job(db: Database, job_id: str) -> None:
    """Skip the worker for tests that only need terminal state."""
    with db.transaction() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'done', finished_at = ? WHERE id = ?",
            (iso(), job_id),
        )