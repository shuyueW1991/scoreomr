"""Job creation, ownership checks and public serialisation."""
from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from .auth import Actor, active_since
from .context import AppContext
from .errors import NotFound, QuotaExceeded, ValidationFailed
from .timeutil import iso, next_reset, utcnow
from .uploads import (
    prepare_input,
    relative_to_data,
    result_file,
    save_upload,
    suffix_of,
    validate_gt,
)

log = logging.getLogger(__name__)
MODES = {"compare", "audiveris", "homr"}
FILE_NAMES = ("best.musicxml", "best.mid", "best.wav", "notes.csv", "piano_roll.png", "report.json")


def _safe_label(name: str | None) -> str:
    value = Path(name or "上传乐谱").name
    value = "".join(ch for ch in value if ch.isprintable())[:120]
    return value or "上传乐谱"


def _suffix_for(file: UploadFile) -> str:
    suffix = suffix_of(file.filename)
    if suffix:
        return suffix
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/tiff": ".tiff",
        "application/pdf": ".pdf",
    }.get((file.content_type or "").lower(), ".png")


def _new_job_id() -> str:
    return uuid.uuid4().hex[:16]


def _database_create(
    ctx: AppContext,
    actor: Actor,
    *,
    job_id: str,
    mode: str,
    label: str,
    job_dir: Path,
    gt_path: Path | None,
) -> dict[str, Any]:
    settings = ctx.settings
    input_path = job_dir / "input.png"
    result_dir = job_dir / "result"
    result_dir.mkdir(parents=True, exist_ok=True)
    try:
        return ctx.db.create_job(
            job_id=job_id,
            user_id=actor.user_id,
            anon_id=actor.anon_id,
            ip_hash=actor.ip_hash,
            mode=mode,
            label=label,
            input_path=relative_to_data(settings, input_path),
            gt_path=relative_to_data(settings, gt_path) if gt_path else None,
            result_dir=relative_to_data(settings, result_dir),
            usage_day=actor.day,
            usage_subject=actor.usage_subject,
            daily_limit=settings.daily_limit,
            max_active=settings.max_active_jobs,
            max_queue=settings.max_queue_length,
            active_since=active_since(settings),
        )
    except QuotaExceeded as exc:
        exc.extra.setdefault("resets_at", iso(next_reset(utcnow(), settings.tz)))
        exc.extra.setdefault("limit", settings.daily_limit)
        raise
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise


async def create_upload_job(
    ctx: AppContext,
    actor: Actor,
    file: UploadFile,
    mode: str,
    gt: UploadFile | None = None,
) -> dict[str, Any]:
    if mode not in MODES:
        raise ValidationFailed("未知的识别模式")
    job_id = _new_job_id()
    job_dir = ctx.settings.jobs_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    settings = ctx.settings
    raw = job_dir / f"upload{_suffix_for(file)}"
    try:
        await save_upload(file, raw, settings.max_upload_mb * 1024 * 1024)
        prepare_input(raw, job_dir)
        gt_path = None
        if gt is not None and (gt.filename or ""):
            gt_raw = job_dir / f"gt_upload{suffix_of(gt.filename) or '.musicxml'}"
            await save_upload(gt, gt_raw, settings.max_gt_mb * 1024 * 1024)
            gt_path = validate_gt(
                gt_raw, job_dir / f"gt{gt_raw.suffix.lower()}", settings.max_gt_mb * 1024 * 1024
            )
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    return _database_create(
        ctx,
        actor,
        job_id=job_id,
        mode=mode,
        label=_safe_label(file.filename),
        job_dir=job_dir,
        gt_path=gt_path,
    )


def create_sample_job(ctx: AppContext, actor: Actor, sample_id: str, mode: str) -> dict[str, Any]:
    if mode not in MODES:
        raise ValidationFailed("未知的识别模式")
    sample = ctx.sample(sample_id)
    if sample is None:
        raise NotFound("样例不存在")
    job_id = _new_job_id()
    job_dir = ctx.settings.jobs_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    try:
        raw = job_dir / "sample.png"
        shutil.copy2(sample["image_path"], raw)
        prepare_input(raw, job_dir)
        gt_path = None
        if sample.get("gt_path"):
            gt_path = job_dir / "gt.musicxml"
            shutil.copy2(sample["gt_path"], gt_path)
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    return _database_create(
        ctx,
        actor,
        job_id=job_id,
        mode=mode,
        label=sample["name"][:120],
        job_dir=job_dir,
        gt_path=gt_path,
    )


def can_access(job: dict[str, Any], actor: Actor) -> bool:
    if job.get("user_id"):
        return bool(actor.user_id and job["user_id"] == actor.user_id)
    return bool(not actor.user and job.get("anon_id") and job["anon_id"] == actor.anon_id)


def accessible_job(ctx: AppContext, actor: Actor, job_id: str) -> dict[str, Any]:
    job = ctx.db.get_job(job_id)
    if job is None or not can_access(job, actor):
        raise NotFound("任务不存在")
    return job


def _report(job: dict[str, Any]) -> dict[str, Any] | None:
    raw = job.get("report_json")
    if not raw:
        return None
    try:
        report = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(report, dict):
        return None
    # Defence in depth: never leak server-side paths even if a future engine
    # adapter adds them to its report.
    report.pop("image", None)
    report.pop("note_table", None)
    for candidate in report.get("candidates") or []:
        if isinstance(candidate, dict):
            candidate.pop("musicxml", None)
            candidate.pop("raw", None)
            candidate.pop("log_tail", None)
    audio = report.get("audio")
    if isinstance(audio, dict):
        audio.pop("wav", None)
        audio.pop("midi", None)
        audio.pop("piano_roll", None)
    return report


def summary(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job["id"],
        "status": job["status"],
        "mode": job["mode"],
        "label": job["label"],
        "created_at": job["created_at"],
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "chosen": job.get("chosen"),
        "confidence": job.get("confidence"),
        "needs_review": bool(job.get("needs_review")),
        "error": job.get("error") if job["status"] == "error" else None,
        "files_ready": job["status"] == "done" and not job.get("files_deleted"),
    }


def detail(ctx: AppContext, job: dict[str, Any]) -> dict[str, Any]:
    payload = summary(job)
    payload["report"] = None if job.get("files_deleted") else _report(job)
    payload["files"] = [
        name
        for name in FILE_NAMES
        if job["status"] == "done" and result_file(ctx.settings, job, name) is not None
    ]
    return payload


def history(ctx: AppContext, actor: Actor, limit: int = 20) -> list[dict[str, Any]]:
    rows = ctx.db.list_jobs(user_id=actor.user_id, anon_id=None if actor.user else actor.anon_id, limit=limit)
    return [summary(row) for row in rows]
