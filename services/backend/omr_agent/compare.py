"""Run several OMR engines on one image and compare their outputs.

The ensemble view is the core product idea: no single engine wins on every
input style, so run the useful ones, validate every candidate with model-free
checks, and let the user see the trade-off.  Ground-truth F1 is an evaluation
signal only; it never drives production selection unless explicitly requested.
"""
from __future__ import annotations

import csv
import json
import logging
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .engines import EngineResult, run_engine
from .metrics import evaluate, extract_events, measure_validity
from .play import extract_notes, piano_roll, synthesize, write_midi
from .preprocess import make_variants, read_gray

log = logging.getLogger(__name__)


@dataclass
class Candidate:
    engine: str
    variant: str
    status: str
    seconds: float
    notes: int = 0
    measures: int = 0
    valid_ratio: float = 0.0
    coverage: float = 0.0
    quality: float = 0.0
    f1: float | None = None
    mock: bool = False
    musicxml: str | None = None


@dataclass
class CompareReport:
    image: str
    style: dict
    mode: str
    candidates: list[Candidate] = field(default_factory=list)
    chosen: str | None = None
    selection: str = "heuristic"
    confidence: float = 0.0
    needs_review: bool = False
    mock: bool = False
    audio: dict = field(default_factory=dict)
    notes: int = 0
    duration_s: float = 0.0
    note_table: str | None = None

    def public(self) -> dict:
        payload = asdict(self)
        payload["image"] = Path(self.image).name
        payload.pop("note_table", None)
        for candidate in payload.get("candidates", []):
            candidate.pop("musicxml", None)
        for key in ("wav", "midi", "piano_roll"):
            payload.get("audio", {}).pop(key, None)
        return payload


def image_style(path: str | Path) -> dict:
    img = read_gray(path)
    h, w = img.shape
    white = float((img > 245).mean())
    black = float((img < 50).mean())
    mid = float(((img >= 60) & (img <= 230)).mean())
    return {
        "width": int(w),
        "height": int(h),
        "mean": round(float(img.mean()), 1),
        "std": round(float(img.std()), 1),
        "white_ratio": round(white, 3),
        "black_ratio": round(black, 3),
        "mid_ratio": round(mid, 3),
        "low_res": bool(w < 1000 or h < 300),
        "scan_like": bool(mid > 0.08 or float(img.mean()) < 220),
    }


def _quality(valid: float, measures: int, notes: int, engine: str, style: dict) -> tuple[float, float]:
    coverage = min(1.0, notes / (measures * 2)) if measures else min(1.0, notes / 20.0)
    structural = valid if measures else 0.0
    prior = 0.18 if (engine == "homr" and style["scan_like"]) else 0.0
    if engine == "audiveris" and not style["scan_like"]:
        prior = 0.18
    return round(0.55 * structural + 0.25 * coverage + 0.20 * prior, 4), round(coverage, 4)


def _write_notes(musicxml: str, path: Path, bpm: float) -> str:
    from music21 import pitch

    rows = extract_events(musicxml)
    spb = 60.0 / bpm
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["part", "measure", "onset_q", "duration_q", "midi", "pitch", "onset_s", "duration_s"])
        for event in rows:
            writer.writerow([
                event.part, int(event.measure), round(event.onset, 4), round(event.duration, 4),
                event.midi, pitch.Pitch(event.midi).nameWithOctave,
                round(event.onset * spb, 4), round(event.duration * spb, 4),
            ])
    return str(path)


def run(
    image: str | Path,
    out_dir: str | Path,
    gt: str | None = None,
    engines: tuple[str, ...] = ("audiveris", "homr"),
    mode: str = "compare",
    oracle: bool = False,
    make_audio: bool = True,
) -> CompareReport:
    image = Path(image)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    variants, meta = make_variants(image, out / "preprocessed")
    upright = next((v for v in variants if v.name == "upright"), variants[0])
    style = image_style(image)
    report = CompareReport(image=str(image), style=style, mode=mode)
    _ = meta

    for engine in engines:
        eng_dir = out / "engines" / engine
        variant = "upright" if engine == "audiveris" else "native"
        source = upright.path if engine == "audiveris" else image
        try:
            result: EngineResult = run_engine(engine, source, eng_dir, variant)
        except Exception as exc:  # noqa: BLE001 - one engine must not kill the job
            log.exception("engine %s crashed", engine)
            result = EngineResult(engine, variant, "failed", error=f"{type(exc).__name__}: {exc}")

        candidate = Candidate(
            engine=engine,
            variant=result.variant,
            status=result.status,
            seconds=round(result.seconds, 2),
            mock=bool(result.meta.get("mock")),
            musicxml=result.musicxml,
        )
        if result.musicxml:
            try:
                events = extract_events(result.musicxml)
                validity = measure_validity(result.musicxml)
                candidate.notes = len(events)
                candidate.measures = int(validity["measures"])
                candidate.valid_ratio = float(validity["valid_ratio"])
                candidate.quality, candidate.coverage = _quality(
                    candidate.valid_ratio, candidate.measures, candidate.notes, engine, style
                )
                if gt:
                    try:
                        candidate.f1 = evaluate(gt, result.musicxml)["f1"]
                    except Exception as exc:  # noqa: BLE001
                        log.warning("ground-truth evaluation failed: %s", exc)
                        candidate.f1 = None
            except Exception as exc:  # noqa: BLE001
                candidate.status = "invalid"
                candidate.notes = 0
                candidate.measures = 0
                log.warning("candidate %s/%s is not usable: %s", engine, variant, exc)
        report.candidates.append(candidate)
        log.info(
            "[%s/%s] %s %.1fs notes=%s valid=%.2f quality=%.2f%s",
            engine, variant, candidate.status, candidate.seconds, candidate.notes,
            candidate.valid_ratio, candidate.quality,
            f" f1={candidate.f1}" if candidate.f1 is not None else "",
        )

    ok = [c for c in report.candidates if c.musicxml and c.status == "ok"]
    if not ok:
        report.needs_review = True
        report.confidence = 0.0
        report.mock = any(c.mock for c in report.candidates)
        (out / "report.json").write_text(
            json.dumps(report.public(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return report

    report.selection = "oracle" if (oracle and gt) else "heuristic"
    if report.selection == "oracle":
        best = max(ok, key=lambda c: (c.f1 if c.f1 is not None else -1, c.quality))
    else:
        best = max(ok, key=lambda c: (c.quality, c.notes))
    report.chosen = f"{best.engine}/{best.variant}"
    report.confidence = best.quality
    report.mock = any(c.mock for c in report.candidates)
    report.needs_review = bool(
        best.notes == 0
        or (best.measures > 0 and best.valid_ratio < 0.5)
        or best.quality < 0.35
        or (best.f1 is not None and best.f1 < 0.9)
    )
    best_xml = out / "best.musicxml"
    assert best.musicxml is not None
    shutil.copy2(best.musicxml, best_xml)

    if make_audio:
        try:
            notes, bpm = extract_notes(best_xml)
            info = synthesize(notes, out / "best.wav")
            info["bpm"] = bpm
            info["midi"] = write_midi(best_xml, out / "best.mid")
            info["piano_roll"] = piano_roll(notes, out / "piano_roll.png", image.stem)
            report.note_table = _write_notes(str(best_xml), out / "notes.csv", bpm)
            report.notes = len(notes)
            report.duration_s = float(info["seconds"])
            report.audio = {
                "seconds": info["seconds"],
                "notes": info["notes"],
                "bpm": bpm,
                "sample_rate": info["sample_rate"],
            }
            shutil.rmtree(out / "preprocessed", ignore_errors=True)
            shutil.rmtree(out / "engines", ignore_errors=True)
        except Exception as exc:  # noqa: BLE001 - MusicXML downloads still work
            log.exception("playback synthesis failed")
            report.audio = {"error": str(exc)[:300]}
            report.needs_review = True

    (out / "report.json").write_text(
        json.dumps(report.public(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--out", default="demo/compare_out")
    ap.add_argument("--gt")
    ap.add_argument("--engines", default="audiveris,homr")
    ap.add_argument("--oracle", action="store_true")
    args = ap.parse_args()
    rep = run(
        args.image,
        args.out,
        gt=args.gt,
        engines=tuple(e.strip() for e in args.engines.split(",") if e.strip()),
        oracle=args.oracle,
    )
    print(json.dumps(rep.public(), indent=2, ensure_ascii=False)[:4000])
