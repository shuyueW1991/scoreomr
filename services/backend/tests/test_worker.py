from __future__ import annotations

import json
from datetime import timedelta

import pytest

from app.timeutil import iso, utcnow
from app.worker import JobProcessingError, Worker
from tests.conftest import create_sample_job


@pytest.fixture(autouse=True)
def matplotlib_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def test_worker_end_to_end_mock(client, settings, tmp_path):
    job = create_sample_job(client)
    worker = Worker(settings)
    claimed = worker.ctx.db.claim_next_job("test-worker")
    assert claimed is not None
    assert claimed["id"] == job["id"]
    worker.process_job(claimed)

    detail = client.get(f"/api/jobs/{job['id']}").json()
    assert detail["status"] == "done"
    assert detail["report"]["mock"] is True
    assert detail["report"]["notes"] > 0
    assert detail["files"] == [
        "best.musicxml", "best.mid", "best.wav", "notes.csv", "piano_roll.png", "report.json"
    ]
    assert not any("musicxml" in candidate for candidate in detail["report"]["candidates"])
    assert str(settings.data_dir) not in json.dumps(detail)

    for name in detail["files"]:
        response = client.get(f"/api/jobs/{job['id']}/files/{name}")
        assert response.status_code == 200, name
        assert len(response.content) > 0

    # Intermediates should not linger on disk.
    job_row = worker.ctx.db.get_job(job["id"])
    result_dir = settings.data_dir / job_row["result_dir"]
    assert not (result_dir / "engines").exists()
    assert not (result_dir / "preprocessed").exists()


def test_worker_failure_marks_job_error(client, settings):
    job = create_sample_job(client)
    worker = Worker(settings)
    claimed = worker.ctx.db.claim_next_job("test-worker")
    assert claimed is not None
    input_path = settings.data_dir / claimed["input_path"]
    input_path.unlink()
    with pytest.raises(JobProcessingError):
        worker.process_job(claimed)
    worker._fail(job["id"], JobProcessingError("输入图片丢失，请重新上传"))

    row = worker.ctx.db.get_job(job["id"])
    assert row["status"] == "error"
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "error"


def test_worker_requeues_orphaned_running_job(client, settings):
    job = create_sample_job(client)
    worker = Worker(settings)
    claimed = worker.ctx.db.claim_next_job("dead-worker")
    assert claimed is not None
    old = iso(utcnow() - timedelta(seconds=600))
    with worker.ctx.db.transaction() as conn:
        conn.execute("UPDATE jobs SET heartbeat_at = ? WHERE id = ?", (old, job["id"]))
    worker.recover_stale()
    row = worker.ctx.db.get_job(job["id"])
    assert row["status"] == "queued"
    assert row["attempts"] == 1


def test_worker_fails_job_after_max_attempts(client, settings):
    job = create_sample_job(client)
    worker = Worker(settings)
    claimed = worker.ctx.db.claim_next_job("dead-worker")
    assert claimed is not None
    old = iso(utcnow() - timedelta(seconds=600))
    with worker.ctx.db.transaction() as conn:
        conn.execute(
            "UPDATE jobs SET heartbeat_at = ?, attempts = 2 WHERE id = ?", (old, job["id"])
        )
    worker.recover_stale()
    row = worker.ctx.db.get_job(job["id"])
    assert row["status"] == "error"