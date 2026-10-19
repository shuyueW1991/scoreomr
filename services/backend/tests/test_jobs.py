from __future__ import annotations

import io
import shutil

import pytest
from PIL import Image
from starlette.testclient import TestClient

from tests.conftest import create_sample_job, finish_job, register


def png_bytes(width: int = 640, height: int = 240) -> bytes:
    image = Image.new("RGB", (width, height), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_different_users_cannot_read_each_others_jobs(client):
    user_a = register(client, email="a@example.com")
    job = create_sample_job(client)
    client.post("/api/auth/logout")
    register(client, email="b@example.com")
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404
    assert client.get(f"/api/jobs/{job['id']}/files/input.png").status_code == 404
    assert user_a["user"]["email"] == "a@example.com"


def test_anonymous_job_is_not_visible_to_new_browser(app):
    with TestClient(app) as first:
        first.get("/api/me")
        job = create_sample_job(first)
    with TestClient(app) as second:
        second.get("/api/me")
        assert second.get(f"/api/jobs/{job['id']}").status_code == 404


def test_job_files_are_allowlisted(client):
    job = create_sample_job(client)
    finish_job(client.app.state.ctx.db, job["id"])
    assert client.get(f"/api/jobs/{job['id']}/files/input.png").status_code == 200
    assert client.get(f"/api/jobs/{job['id']}/files/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert client.get(f"/api/jobs/{job['id']}/files/nope.txt").status_code == 404


def test_upload_rejects_non_image(client):
    response = client.post(
        "/api/jobs",
        files={"file": ("notes.txt", b"not an image", "text/plain")},
        data={"mode": "compare"},
    )
    assert response.status_code == 415
    assert client.get("/api/me").json()["quota"]["remaining_today"] == 1


def test_upload_accepts_png(client):
    response = client.post(
        "/api/jobs",
        files={"file": ("score.png", png_bytes(), "image/png")},
        data={"mode": "compare"},
    )
    assert response.status_code == 201, response.text
    job = response.json()["job"]
    ctx = client.app.state.ctx
    input_path = ctx.settings.data_dir / ctx.db.get_job(job["id"])["input_path"]
    assert input_path.exists()
    with Image.open(input_path) as image:
        assert image.format == "PNG"
        assert image.mode == "RGB"


def test_gt_with_doctype_is_rejected_and_quota_is_not_consumed(client):
    response = client.post(
        "/api/jobs",
        files={
            "file": ("score.png", png_bytes(), "image/png"),
            "gt": (
                "gt.musicxml",
                b'<?xml version="1.0"?><!DOCTYPE score [<!ENTITY x SYSTEM "file:///etc/passwd">]><score/>',
                "application/xml",
            ),
        },
        data={"mode": "compare", "use_gt": "1"},
    )
    assert response.status_code == 415
    assert client.get("/api/me").json()["quota"]["remaining_today"] == 1


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="poppler not installed")
def test_pdf_first_page_is_rasterised(client):
    image = Image.new("RGB", (800, 300), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PDF")
    response = client.post(
        "/api/jobs",
        files={"file": ("score.pdf", buffer.getvalue(), "application/pdf")},
        data={"mode": "compare"},
    )
    assert response.status_code == 201, response.text
    ctx = client.app.state.ctx
    job = ctx.db.get_job(response.json()["job"]["id"])
    assert job is not None
    input_path = ctx.settings.data_dir / job["input_path"]
    with Image.open(input_path) as produced:
        assert produced.format == "PNG"
        assert produced.width >= 800


def test_sample_images_are_public(client):
    response = client.get("/api/samples/clean_piano/image")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert client.get("/api/samples/nope/image").status_code == 404
