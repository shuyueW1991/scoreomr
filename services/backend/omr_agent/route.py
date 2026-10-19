"""Engine-aware routing demo.

The important empirical finding from our tests is that engines are
complementary: Audiveris is excellent on clean, high-resolution engraving,
while homr is much better on a low-resolution scan.  Routing on *input
quality* is therefore more useful than picking one "best" engine.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2

from .engines import run_engine
from .metrics import evaluate, extract_events, measure_validity
from .play import extract_notes, piano_roll, synthesize, write_midi
from .preprocess import make_variants, read_gray


@dataclass
class RouteReport:
    image: str
    quality: dict
    engine: str
    variant: str
    status: str
    seconds: float
    musicxml: str | None = None
    notes: int = 0
    measures: int = 0
    valid_ratio: float = 0.0
    f1: float | None = None
    audio: dict = field(default_factory=dict)
    note_table: str | None = None


def image_quality(path: str | Path) -> dict:
    img = read_gray(path)
    h, w = img.shape
    blur = float(cv2.Laplacian(img, cv2.CV_64F).var())
    ink = float((img < 200).mean())
    # A pragmatic gate: below ~1000 px wide, staff spacing is usually < 6 px.
    low_res = w < 1000 or h < 300
    return {
        "width": int(w),
        "height": int(h),
        "lap_var": round(blur, 2),
        "ink_ratio": round(ink, 4),
        "low_res": bool(low_res),
        "route": "homr-native" if low_res else "audiveris-upright",
    }


def run(image: str | Path, out_dir: str | Path, gt: str | None = None) -> RouteReport:
    image = Path(image)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    variants, meta = make_variants(image, out / "preprocessed")
    quality = image_quality(image)
    if quality["low_res"]:
        res = run_engine("homr", image, out / "engines" / "homr", "native")
        used_variant = "original"
    else:
        upright = next(v for v in variants if v.name == "upright")
        res = run_engine("audiveris", upright.path, out / "engines" / "audiveris", "upright")
        used_variant = "upright"
    rep = RouteReport(
        image=str(image.resolve()),
        quality=quality,
        engine=res.engine,
        variant=used_variant,
        status=res.status,
        seconds=round(res.seconds, 2),
        musicxml=res.musicxml,
    )
    if res.musicxml:
        rep.notes = len(extract_events(res.musicxml))
        mv = measure_validity(res.musicxml)
        rep.measures = int(mv["measures"])
        rep.valid_ratio = float(mv["valid_ratio"])
        if gt:
            rep.f1 = evaluate(gt, res.musicxml)["f1"]
        import shutil

        shutil.copy2(res.musicxml, out / "best.musicxml")
        try:
            notes, bpm = extract_notes(out / "best.musicxml")
            info = synthesize(notes, out / "best.wav")
            info["midi"] = write_midi(out / "best.musicxml", out / "best.mid")
            info["piano_roll"] = piano_roll(notes, out / "piano_roll.png", image.stem)
            info["bpm"] = bpm
            rep.audio = info
            import csv
            from music21 import pitch

            rows = extract_events(str(out / "best.musicxml"))
            spb = 60.0 / bpm
            with (out / "notes.csv").open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["part", "measure", "onset_q", "duration_q", "midi", "pitch",
                                 "onset_s", "duration_s"])
                for e in rows:
                    writer.writerow([e.part, int(e.measure), e.onset, e.duration, e.midi,
                                     pitch.Pitch(e.midi).nameWithOctave,
                                     round(e.onset * spb, 4), round(e.duration * spb, 4)])
            rep.note_table = str(out / "notes.csv")
        except Exception as exc:  # noqa: BLE001
            rep.audio = {"error": str(exc)}
    (out / "route_report.json").write_text(json.dumps(asdict(rep), indent=2, ensure_ascii=False))
    return rep


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--out", default="demo/route_out")
    ap.add_argument("--gt")
    args = ap.parse_args()
    rep = run(args.image, args.out, args.gt)
    print(json.dumps(asdict(rep), indent=2, ensure_ascii=False)[:3000])
