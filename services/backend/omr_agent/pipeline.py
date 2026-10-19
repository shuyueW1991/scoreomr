"""A small, auditable agent for score screenshots.

Stages:
  1. preprocess -> upright / CLAHE / binary views
  2. run one or more OMR engines on the views
  3. validate each candidate with model-free musical checks
  4. choose the best candidate (or, with --oracle, the one with best GT F1)
  5. export MusicXML, MIDI, WAV and a JSON/HTML report

This is intentionally a state machine, not a free-form LLM loop: every stage
is deterministic, inspectable, and can be replaced independently.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .engines import EngineResult, run_engine
from .metrics import evaluate, extract_events, measure_validity
from .play import extract_notes, piano_roll, synthesize, write_midi
from .preprocess import Variant, make_variants

ENGINE_PRIOR = {"audiveris": 0.15, "homr": 0.10, "oemer": 0.05, "transcoda": 0.05}


@dataclass
class Candidate:
    engine: str
    variant: str
    status: str
    musicxml: str | None
    seconds: float
    notes: int = 0
    measures: int = 0
    valid_ratio: float = 0.0
    parse_ok: bool = False
    quality: float = 0.0
    f1: float | None = None
    error: str = ""
    log_tail: str = ""


@dataclass
class Report:
    image: str
    preprocess: dict
    candidates: list[Candidate] = field(default_factory=list)
    chosen: str | None = None
    confidence: float = 0.0
    needs_review: bool = False
    audio: dict = field(default_factory=dict)
    notes: int = 0
    duration_s: float = 0.0
    note_table: str | None = None


def _stats(mx: str) -> tuple[int, int, float, bool]:
    try:
        events = extract_events(mx)
        mv = measure_validity(mx)
        return len(events), int(mv["measures"]), float(mv["valid_ratio"]), True
    except Exception:
        return 0, 0, 0.0, False


def write_note_table(musicxml: str | Path, out_csv: str | Path, bpm: float = 100.0) -> str:
    """One row per notehead: the most concrete form of 'note for note'."""
    import csv

    from music21 import pitch

    from .metrics import extract_events

    events = extract_events(str(musicxml))
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    spb = 60.0 / bpm
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["part", "measure", "onset_q", "duration_q", "midi", "pitch", "onset_s", "duration_s"])
        for e in events:
            w.writerow([
                e.part, int(e.measure), round(e.onset, 4), round(e.duration, 4),
                e.midi, pitch.Pitch(e.midi).nameWithOctave,
                round(e.onset * spb, 4), round(e.duration * spb, 4),
            ])
    return str(out_csv)


def run(
    image: str,
    out_dir: str,
    engines: list[str] | None = None,
    variants: list[str] | None = None,
    gt: str | None = None,
    oracle: bool = False,
    make_audio: bool = True,
) -> Report:
    t_start = time.time()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    engines = engines or ["audiveris"]
    pre_dir = out / "preprocessed"
    all_variants, meta = make_variants(image, pre_dir)
    if variants:
        all_variants = [v for v in all_variants if v.name in variants] or all_variants

    report = Report(image=str(Path(image).resolve()), preprocess=meta)
    results: list[EngineResult] = []
    for variant in all_variants:
        for engine_name in engines:
            eng_dir = out / "engines" / engine_name / variant.name
            try:
                res = run_engine(engine_name, variant.path, eng_dir, variant.name)
            except Exception as exc:  # noqa: BLE001
                res = EngineResult(engine_name, variant.name, "failed", error=str(exc))
            results.append(res)
            cand = Candidate(
                engine=engine_name,
                variant=variant.name,
                status=res.status,
                musicxml=res.musicxml,
                seconds=round(res.seconds, 2),
                error=res.error[-600:],
                log_tail=res.log[-600:],
            )
            if res.musicxml:
                notes, measures, valid, ok = _stats(res.musicxml)
                cand.notes, cand.measures, cand.valid_ratio, cand.parse_ok = notes, measures, valid, ok
                coverage = min(1.0, notes / max(1, measures * 2)) if measures else min(1.0, notes / 8)
                # A missing time signature makes measure validity *unknown*, not bad:
                # mid-piece screenshots legitimately inherit it from an earlier page.
                structural = valid if measures else 0.5
                cand.quality = round(
                    0.50 * structural + 0.30 * coverage + 0.20 * ENGINE_PRIOR.get(engine_name, 0.0), 4
                )
                if gt:
                    try:
                        cand.f1 = evaluate(gt, res.musicxml)["f1"]
                    except Exception:
                        cand.f1 = None
            report.candidates.append(cand)
            print(
                f"[{engine_name}/{variant.name}] {res.status} "
                f"{cand.seconds:.1f}s notes={cand.notes} valid={cand.valid_ratio:.2f} "
                f"q={cand.quality:.2f}" + (f" f1={cand.f1}" if cand.f1 is not None else "")
            )

    ok = [c for c in report.candidates if c.musicxml and c.status == "ok"]
    if not ok:
        report.chosen = None
        (out / "report.json").write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False))
        return report
    if oracle and gt:
        best = max(ok, key=lambda c: (c.f1 if c.f1 is not None else -1, c.quality))
    else:
        best = max(ok, key=lambda c: (c.quality, c.notes))
    report.chosen = f"{best.engine}/{best.variant}"
    report.confidence = best.quality
    report.needs_review = (
        best.notes == 0
        or (best.measures > 0 and best.valid_ratio < 0.5)
        or best.quality < 0.35
    )
    best_xml = out / "best.musicxml"
    import shutil

    shutil.copy2(best.musicxml, best_xml)

    if make_audio:
        try:
            notes, bpm = extract_notes(best_xml)
            info = synthesize(notes, out / "best.wav")
            info["bpm"] = bpm
            info["midi"] = write_midi(best_xml, out / "best.mid")
            info["piano_roll"] = piano_roll(notes, out / "piano_roll.png", Path(image).stem)
            report.audio = info
            report.notes = len(notes)
            report.duration_s = info["seconds"]
            report.note_table = write_note_table(best_xml, out / "notes.csv", bpm)
            if report.needs_review:
                print("WARNING: low confidence; inspect notes.csv / best.musicxml before trusting playback")
        except Exception as exc:  # noqa: BLE001
            report.audio = {"error": str(exc)}

    report.preprocess["elapsed_s"] = round(time.time() - t_start, 2)
    (out / "report.json").write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False))
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the OMR agent on a score screenshot")
    ap.add_argument("image")
    ap.add_argument("--out", default="demo/agent_out")
    ap.add_argument("--engines", default="audiveris", help="comma separated: audiveris,oemer,homr")
    ap.add_argument("--variants", default="upright", help="comma separated: upright,clahe,binary")
    ap.add_argument("--gt", default=None, help="optional ground-truth MusicXML for evaluation")
    ap.add_argument("--oracle", action="store_true", help="choose by GT F1 (evaluation only)")
    ap.add_argument("--no-audio", action="store_true")
    args = ap.parse_args()
    rep = run(
        args.image,
        args.out,
        engines=[e.strip() for e in args.engines.split(",") if e.strip()],
        variants=[v.strip() for v in args.variants.split(",") if v.strip()],
        gt=args.gt,
        oracle=args.oracle,
        make_audio=not args.no_audio,
    )
    print(json.dumps(asdict(rep), indent=2, ensure_ascii=False)[:4000])


if __name__ == "__main__":
    main()
