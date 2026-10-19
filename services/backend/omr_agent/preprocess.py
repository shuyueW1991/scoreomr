"""Image preparation for OMR.

Nothing here is music-specific magic: the goal is to give every engine a
clean, upright, adequately sized page, and to produce a few *views* of the
same page so that the agent can cross-check engines/variants later.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class Variant:
    name: str
    path: Path
    note: str


def read_gray(path: str | Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"cannot read image: {path}")
    return img


def write_gray(path: str | Path, img: np.ndarray) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(path.suffix or ".png", img)
    if not ok:
        raise ValueError(f"cannot encode image: {path}")
    buf.tofile(str(path))


def content_bbox(img: np.ndarray, margin: int = 24) -> tuple[int, int, int, int]:
    """Bounding box of ink, with a white margin."""
    ink = (img < 245).astype(np.uint8)
    cols = np.where(ink.sum(axis=0) > 0)[0]
    rows = np.where(ink.sum(axis=1) > 0)[0]
    if len(cols) == 0 or len(rows) == 0:
        return 0, 0, img.shape[1], img.shape[0]
    x0, x1 = max(0, cols[0] - margin), min(img.shape[1], cols[-1] + margin)
    y0, y1 = max(0, rows[0] - margin), min(img.shape[0], rows[-1] + margin)
    return int(x0), int(y0), int(x1), int(y1)


def _rotate(img: np.ndarray, angle: float) -> np.ndarray:
    h, w = img.shape[:2]
    center = (w / 2, h / 2)
    m = cv2.getRotationMatrix2D(center, angle, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    m[0, 2] += nw / 2 - center[0]
    m[1, 2] += nh / 2 - center[1]
    return cv2.warpAffine(
        img, m, (nw, nh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=255
    )


def estimate_skew(img: np.ndarray) -> float:
    """Find the rotation that makes staff lines most horizontal.

    Horizontal projection variance is maximal when the five staff lines of a
    system collapse into a few strong peaks.  This works on scans and photos
    and does not need Hough line bookkeeping.
    """
    small = img
    if img.shape[1] > 1400:
        scale = 1400 / img.shape[1]
        small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    def score(angle: float) -> float:
        # Rotate grayscale (white border) and count ink per row.  Using a
        # 0/1 array here would let the 255-valued border dominate the score.
        rot = _rotate(small, angle)
        ink = (rot < 190).astype(np.float64)
        proj = ink.sum(axis=1)
        return float(np.var(proj))

    coarse = max(np.arange(-6.0, 6.01, 0.5), key=score)
    fine = max(np.arange(coarse - 0.5, coarse + 0.51, 0.1), key=score)
    return round(float(fine), 2)


def deskew(img: np.ndarray, angle: float | None = None) -> tuple[np.ndarray, float]:
    angle = estimate_skew(img) if angle is None else angle
    if abs(angle) < 0.1:
        return img, 0.0
    return _rotate(img, angle), angle


def binarize(img: np.ndarray) -> np.ndarray:
    # A light denoise first; adaptive threshold keeps faint staff lines.
    blur = cv2.GaussianBlur(img, (3, 3), 0)
    return cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 12
    )


def upscale(img: np.ndarray, min_width: int = 1800, max_width: int = 3200) -> np.ndarray:
    h, w = img.shape[:2]
    if w >= min_width:
        return img
    target = min(max_width, max(min_width, w * 2))
    scale = target / w
    return cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def split_systems(img: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Rough system segmentation using horizontal projection.

    Returns boxes (x0, y0, x1, y1).  For a single-system screenshot it returns
    one box covering the content.  This is deliberately conservative: engines
    that do their own layout analysis (Audiveris, oemer) get the whole page.
    """
    ink = (img < 220).astype(np.uint8)
    row = ink.sum(axis=1).astype(np.float64)
    if row.max() == 0:
        return [(0, 0, img.shape[1], img.shape[0])]
    # smooth and threshold at a fraction of the strongest staff-line row
    k = max(3, img.shape[1] // 200)
    smooth = np.convolve(row, np.ones(k) / k, mode="same")
    thresh = max(0.08 * smooth.max(), 2.0)
    active = smooth > thresh
    runs = []
    start = None
    for y, on in enumerate(active):
        if on and start is None:
            start = y
        elif not on and start is not None:
            if y - start > 8:
                runs.append((start, y))
            start = None
    if start is not None:
        runs.append((start, len(active)))
    if not runs:
        return [(0, 0, img.shape[1], img.shape[0])]
    # merge runs separated by less than a staff height
    merged = [list(runs[0])]
    for a, b in runs[1:]:
        if a - merged[-1][1] < 28:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    boxes = []
    for y0, y1 in merged:
        if y1 - y0 < 40:
            continue
        boxes.append((0, max(0, y0 - 12), img.shape[1], min(img.shape[0], y1 + 12)))
    return boxes or [(0, 0, img.shape[1], img.shape[0])]


def make_variants(src: str | Path, out_dir: str | Path) -> tuple[list[Variant], dict]:
    """Produce upright, enhanced and binarized views plus diagnostics."""
    src = Path(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    img = read_gray(src)
    meta = {"input": str(src), "input_size": [int(img.shape[1]), int(img.shape[0])]}

    x0, y0, x1, y1 = content_bbox(img)
    cropped = img[y0:y1, x0:x1]
    upright, angle = deskew(cropped)
    meta["skew_degrees"] = angle
    meta["content_bbox"] = [x0, y0, x1, y1]

    variants: list[Variant] = []
    base = upscale(upright, 1800, 3200)
    p = out_dir / "page_upright.png"
    write_gray(p, base)
    variants.append(Variant("upright", p, "deskewed, upscaled, contrast normalized"))

    eq = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(base)
    p = out_dir / "page_clahe.png"
    write_gray(p, eq)
    variants.append(Variant("clahe", p, "local contrast enhancement"))

    bw = binarize(base)
    p = out_dir / "page_binary.png"
    write_gray(p, bw)
    variants.append(Variant("binary", p, "adaptive binarization"))

    return variants, meta


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--out", default="demo/preprocessed")
    args = ap.parse_args()
    variants, meta = make_variants(args.image, args.out)
    print(json.dumps(meta, indent=2))
    for v in variants:
        print(v.name, v.path, v.note)
