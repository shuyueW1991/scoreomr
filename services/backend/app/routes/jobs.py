"""Job creation, polling, file delivery and demo samples."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..auth import Actor
from ..context import AppContext, public_sample
from ..deps import get_actor, get_context
from ..errors import NotFound
from ..jobs import (
    accessible_job,
    create_sample_job,
    create_upload_job,
    detail,
    history,
    summary,
)
from ..uploads import result_file

router = APIRouter(prefix="/api", tags=["jobs"])

MEDIA = {
    "best.musicxml": "application/vnd.recordare.musicxml+xml",
    "best.mid": "audio/midi",
    "best.wav": "audio/wav",
    "notes.csv": "text/csv; charset=utf-8",
    "piano_roll.png": "image/png",
    "report.json": "application/json",
    "input.png": "image/png",
}
DOWNLOAD_NAMES = {
    "best.musicxml": "score.musicxml",
    "best.mid": "score.mid",
    "best.wav": "score.wav",
    "notes.csv": "notes.csv",
    "piano_roll.png": "piano_roll.png",
    "report.json": "report.json",
}
INLINE = {"input.png", "piano_roll.png"}


class RunSample(BaseModel):
    mode: str = "compare"


@router.get("/samples")
def samples(ctx: AppContext = Depends(get_context)) -> dict:
    return {"samples": [public_sample(s) for s in ctx.samples]}


@router.get("/samples/{sample_id}/image")
def sample_image(sample_id: str, ctx: AppContext = Depends(get_context)) -> FileResponse:
    sample = ctx.sample(sample_id)
    if sample is None or not Path(sample["image_path"]).is_file():
        raise NotFound("样例不存在")
    return FileResponse(
        sample["image_path"],
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/samples/{sample_id}/run", status_code=201)
def run_sample(
    sample_id: str,
    payload: RunSample,
    actor: Actor = Depends(get_actor),
    ctx: AppContext = Depends(get_context),
) -> dict:
    job = create_sample_job(ctx, actor, sample_id, payload.mode)
    return {"job": summary(job)}


@router.post("/jobs", status_code=201)
async def create_job(
    file: UploadFile = File(...),
    mode: str = Form("compare"),
    gt: UploadFile | None = File(default=None),
    actor: Actor = Depends(get_actor),
    ctx: AppContext = Depends(get_context),
) -> dict:
    job = await create_upload_job(ctx, actor, file, mode, gt)
    return {"job": summary(job)}


@router.get("/jobs")
def list_jobs(actor: Actor = Depends(get_actor), ctx: AppContext = Depends(get_context)) -> dict:
    return {"jobs": history(ctx, actor)}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, actor: Actor = Depends(get_actor), ctx: AppContext = Depends(get_context)) -> dict:
    job = accessible_job(ctx, actor, job_id)
    return detail(ctx, job)


@router.get("/jobs/{job_id}/files/{name}")
def get_file(
    job_id: str,
    name: str,
    actor: Actor = Depends(get_actor),
    ctx: AppContext = Depends(get_context),
) -> FileResponse:
    job = accessible_job(ctx, actor, job_id)
    path = result_file(ctx.settings, job, name)
    if path is None:
        raise NotFound("文件尚未生成或已被清理")
    headers = {"Cache-Control": "private, no-store"}
    if name in INLINE:
        return FileResponse(path, media_type=MEDIA[name], headers=headers)
    return FileResponse(
        path,
        media_type=MEDIA[name],
        filename=DOWNLOAD_NAMES[name],
        headers=headers,
    )