from __future__ import annotations

from tests.conftest import create_sample_job, finish_job, register


def test_anonymous_free_quota_is_one_per_day(client):
    client.get("/api/me")
    job = create_sample_job(client)
    finish_job(client.app.state.ctx.db, job["id"])

    again = client.get("/api/me").json()["quota"]
    assert again["remaining_today"] == 0

    blocked = client.post("/api/samples/clean_piano/run", json={"mode": "compare"})
    assert blocked.status_code == 429
    body = blocked.json()["error"]
    assert body["code"] == "quota_exceeded"
    assert body["resets_at"]


def test_create_response_returns_post_consumption_quota(client):
    client.get("/api/me")
    response = client.post("/api/samples/clean_piano/run", json={"mode": "compare"})
    assert response.status_code == 201
    assert response.json()["quota"]["remaining_today"] == 0


def test_active_job_returns_existing_job_id(client):
    client.get("/api/me")
    job = create_sample_job(client)
    blocked = client.post("/api/samples/clean_piano/run", json={"mode": "compare"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "active_job_exists"
    assert blocked.json()["error"]["active_job"] == job["id"]


def test_registered_free_user_has_own_quota_key(client):
    register(client)
    job = create_sample_job(client)
    finish_job(client.app.state.ctx.db, job["id"])
    quota = client.get("/api/me").json()["quota"]
    assert quota["used_today"] == 1
    assert quota["remaining_today"] == 0
