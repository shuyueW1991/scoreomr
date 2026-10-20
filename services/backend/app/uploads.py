"""Upload validation and image/PDF normalisation.

Everything the worker sees is a single RGB PNG under ``DATA_DIR/jobs/<id>``.
That keeps engine adapters simple and prevents user filenames or paths from
reaching the shell.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import Settings
from .errors import FileTooLarge, UnsupportedFile, ValidationFailed

ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
ALLOWED_GT_SUFFIXES = {".xml", ".musicxml", ".mxl"}
CHUNK = 1024 * 1024
MAX_PIXELS = 80_000_000
MAX_LONG_EDGE = 5000

Image.MAX_IMAGE_PIXELS = MAX_PIXELS


async def save_upload(file: UploadFile, destination: Path, max_bytes: int) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with destination.open("wb") as fh:
            while True:
                chunk = await file.read(CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise FileTooLarge(f"文件超过 {max_bytes // (1024 * 1024)} MB 限制")
                fh.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if written == 0:
        destination.unlink(missing_ok=True)
        raise ValidationFailed("上传的文件是空的")
    return written


def suffix_of(filename: str | None) -> str:
    return Path(filename or "").suffix.lower()


def _has_xml_doctype(path: Path) -> bool:
    try:
        head = path.read_bytes()[:4096].upper()
    except OSError:
        return False
    return b"<!DOCTYPE" in head or b"<!ENTITY" in head


def validate_gt(src: Path, destination: Path, max_bytes: int) -> Path:
    if src.stat().st_size > max_bytes:
        raise FileTooLarge(f"真值文件超过 {max_bytes // (1024 * 1024)} MB 限制")
    if src.suffix.lower() not in ALLOWED_GT_SUFFIXES:
        raise UnsupportedFile("真值只支持 .musicxml / .xml / .mxl")
    if src.suffix.lower() != ".mxl" and _has_xml_doctype(src):
        raise UnsupportedFile("真值 XML 不能包含 DOCTYPE/ENTITY")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != destination.resolve():
        shutil.move(str(src), destination)
    return destination


def _flatten_on_white(im: Image.Image) -> Image.Image:
    if im.mode in {"RGBA", "LA"} or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(background, rgba).convert("RGB")
    return im.convert("RGB")


def normalize_image(src: Path, destination: Path) -> Path:
    try:
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            im.load()
            if im.width * im.height > MAX_PIXELS:
                raise ValidationFailed("图片像素过大（超过 8000 万像素）")
            rgb = _flatten_on_white(im)
            longest = max(rgb.size)
            if longest > MAX_LONG_EDGE:
                scale = MAX_LONG_EDGE / longest
                rgb = rgb.resize(
                    (max(1, int(rgb.width * scale)), max(1, int(rgb.height * scale))),
                    Image.Resampling.LANCZOS,
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            rgb.save(destination, format="PNG", optimize=False, compress_level=6)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise UnsupportedFile(f"无法读取图片：{exc}") from exc
    finally:
        src.unlink(missing_ok=True)
    return destination


def normalize_pdf(src: Path, destination: Path) -> Path:
    exe = shutil.which("pdftoppm")
    if not exe:
        raise ValidationFailed("服务器缺少 pdftoppm，无法处理 PDF")
    prefix = destination.with_name(f"{destination.stem}_pdf")
    try:
        proc = subprocess.run(
            [exe, "-png", "-r", "200", "-f", "1", "-l", "1", "-singlefile", str(src), str(prefix)],
            capture_output=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValidationFailed("PDF 转图片超时") from exc
    produced = prefix.with_suffix(".png")
    if proc.returncode != 0 or not produced.exists():
        raise UnsupportedFile("PDF 无法解析（可能是加密或损坏文件）")
    try:
        return normalize_image(produced, destination)
    finally:
        src.unlink(missing_ok=True)


def prepare_input(raw: Path, job_dir: Path) -> Path:
    """Turn a validated upload into ``job_dir/input.png``."""
    suffix = raw.suffix.lower()
    destination = job_dir / "input.png"
    if suffix == ".pdf":
        return normalize_pdf(raw, destination)
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raw.unlink(missing_ok=True)
        raise UnsupportedFile("只支持 PNG / JPG / WebP / TIFF / BMP / PDF")
    return normalize_image(raw, destination)


def job_paths(settings: Settings, job_id: str) -> tuple[Path, Path]:
    base = settings.jobs_dir / job_id
    return base, base / "result"


def relative_to_data(settings: Settings, path: Path) -> str:
    return path.resolve().relative_to(settings.data_dir.resolve()).as_posix()


def resolve_data_path(settings: Settings, relative: str) -> Path:
    base = settings.data_dir.resolve()
    path = (base / relative).resolve()
    if not path.is_relative_to(base):
        raise ValidationFailed("非法路径")
    return path


def result_file(settings: Settings, job: dict, name: str) -> Path | None:
    allowed = {
        "input.png",
        "best.musicxml",
        "best.mid",
        "best.wav",
        "notes.csv",
        "piano_roll.png",
        "report.json",
    }
    if name not in allowed:
        return None
    if name == "input.png":
        path = resolve_data_path(settings, job["input_path"])
    else:
        path = resolve_data_path(settings, job["result_dir"]) / name
    if not path.is_file():
        return None
    return path
