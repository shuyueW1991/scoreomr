from __future__ import annotations

from tests.conftest import create_sample_job, register


def test_register_login_logout(client):
    user = register(client)
    assert user["user"]["email"] == "test@example.com"
    assert client.get("/api/me").json()["user"]["email"] == "test@example.com"

    duplicate = client.post(
        "/api/auth/register", json={"email": "TEST@example.com", "password": "password123"}
    )
    assert duplicate.status_code == 409

    bad = client.post(
        "/api/auth/login", json={"email": "test@example.com", "password": "wrongpass"}
    )
    assert bad.status_code == 401

    good = client.post(
        "/api/auth/login", json={"email": "test@example.com", "password": "password123"}
    )
    assert good.status_code == 200

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert client.get("/api/me").json()["user"] is None


def test_invalid_email_and_short_password(client):
    bad_email = client.post(
        "/api/auth/register", json={"email": "not-an-email", "password": "password123"}
    )
    assert bad_email.status_code == 400
    short = client.post(
        "/api/auth/register", json={"email": "a@example.com", "password": "short"}
    )
    assert short.status_code == 422


def test_anonymous_jobs_are_claimed_on_register(client):
    client.get("/api/me")
    job = create_sample_job(client)
    register(client, email="claim@example.com")
    jobs = client.get("/api/jobs").json()["jobs"]
    assert any(item["id"] == job["id"] for item in jobs)
    assert client.get(f"/api/jobs/{job['id']}").status_code == 200
