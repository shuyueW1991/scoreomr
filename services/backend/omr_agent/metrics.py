"""Note-level evaluation for OMR output against a MusicXML ground truth.

The metric intentionally works on *noteheads*, not on notation tokens:
a chord of three notes counts as three noteheads, and matching requires
the same MIDI pitch plus a nearby onset/duration.  This is the metric that
matters for "can it be played note for note".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from music21 import chord, converter, note, stream


@dataclass(frozen=True)
class NoteEvent:
    part: int
    measure: float
    onset: float          # quarter notes from the start of the part
    duration: float       # quarter notes
    midi: int
    chord_size: int = 1


def _part_events(part: stream.Part, part_index: int) -> list[NoteEvent]:
    """Flatten all noteheads, including notes nested in <voice> elements.

    music21's Measure.notes only returns direct children; real MusicXML
    (and OLiMPiC in particular) nests notes inside voices, so recurse instead.
    """
    events: list[NoteEvent] = []
    for el in part.recurse().notes:
        measure = el.getContextByClass(stream.Measure)
        if isinstance(el, note.Note):
            pitches = [el.pitch.midi]
        elif isinstance(el, chord.Chord):
            pitches = sorted(p.midi for p in el.pitches)
        else:
            continue
        dur = float(el.duration.quarterLength)
        onset = float(el.getOffsetInHierarchy(part))
        for midi in pitches:
            events.append(
                NoteEvent(
                    part=part_index,
                    measure=float(measure.number or 0) if measure is not None else 0.0,
                    onset=onset,
                    duration=dur,
                    midi=int(midi),
                    chord_size=len(pitches),
                )
            )
    return events


def extract_events(path_or_score) -> list[NoteEvent]:
    score = (
        converter.parse(path_or_score)
        if isinstance(path_or_score, (str, bytes))
        else path_or_score
    )
    events: list[NoteEvent] = []
    for i, part in enumerate(score.parts):
        events.extend(_part_events(part, i))
    events.sort(key=lambda e: (e.part, e.onset, e.midi))
    return events


def _match(
    gt: list[NoteEvent],
    pred: list[NoteEvent],
    onset_tol: float,
    dur_tol: float,
    require_same_part: bool = False,
    require_pitch: bool = True,
) -> tuple[int, list[tuple[int, int]]]:
    """Greedy one-to-one matching, nearest onset first."""
    used = [False] * len(pred)
    pairs: list[tuple[int, int]] = []
    # Sort GT by how constrained it is: sparse onsets first.
    for gi, g in enumerate(gt):
        best = None
        best_cost = 1e9
        for pi, p in enumerate(pred):
            if used[pi]:
                continue
            if require_same_part and g.part != p.part:
                continue
            if abs(g.onset - p.onset) > onset_tol:
                continue
            if abs(g.duration - p.duration) > dur_tol:
                continue
            if require_pitch and g.midi != p.midi:
                continue
            cost = abs(g.onset - p.onset) + 0.25 * abs(g.duration - p.duration)
            if cost < best_cost:
                best_cost, best = cost, pi
        if best is not None:
            used[best] = True
            pairs.append((gi, best))
    return len(pairs), pairs


def evaluate(
    gt_path: str,
    pred_path: str,
    onset_tol: float = 0.26,
    dur_tol: float = 0.26,
) -> dict:
    gt = extract_events(gt_path)
    pred = extract_events(pred_path)
    tp, pairs = _match(gt, pred, onset_tol, dur_tol)
    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(gt) if gt else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    # Onset matching ignoring pitch: how often is the rhythm/attack right?
    onset_tp, onset_pairs = _match(gt, pred, onset_tol, dur_tol, require_pitch=False)
    pitch_ok = sum(1 for gi, pi in onset_pairs if gt[gi].midi == pred[pi].midi)
    # Duration correctness among correctly pitched notes.
    dur_ok = sum(
        1
        for gi, pi in pairs
        if abs(gt[gi].duration - pred[pi].duration) <= 0.01
    )
    return {
        "gt_noteheads": len(gt),
        "pred_noteheads": len(pred),
        "tp": tp,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "onset_matched": onset_tp,
        "pitch_accuracy_given_onset": round(pitch_ok / onset_tp, 4) if onset_tp else 0.0,
        "duration_exact_given_match": round(dur_ok / tp, 4) if tp else 0.0,
    }


def measure_validity(path: str) -> dict:
    """Fraction of measures whose content fills the nominal measure length.

    OMR systems frequently drop/duplicate a note, which shows up as a measure
    that is too short or too long.  This is a cheap, model-free confidence cue.
    """
    score = converter.parse(path)
    total = valid = 0
    details = []
    for pi, part in enumerate(score.parts):
        for m in part.getElementsByClass(stream.Measure):
            ts = m.timeSignature
            if ts is None:
                # inherit from the previous measure in this part
                prev = m.previous()
                while prev is not None and not isinstance(prev, stream.Measure):
                    prev = prev.previous()
                ts = prev.timeSignature if isinstance(prev, stream.Measure) else None
            if ts is None:
                continue
            nominal = float(ts.barDuration.quarterLength)
            # highest end position of any note/rest in the measure,
            # including notes nested inside voices.
            ends = [
                float(e.getOffsetInHierarchy(m)) + float(e.duration.quarterLength)
                for e in m.recurse().notesAndRests
            ]
            actual = max(ends) if ends else 0.0
            total += 1
            ok = abs(actual - nominal) <= 0.26
            valid += int(ok)
            details.append(
                {
                    "part": pi,
                    "measure": m.number,
                    "nominal": nominal,
                    "actual": round(actual, 3),
                    "ok": ok,
                }
            )
    return {
        "measures": total,
        "valid": valid,
        "valid_ratio": round(valid / total, 4) if total else 0.0,
        "details": details,
    }


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser()
    ap.add_argument("gt")
    ap.add_argument("pred")
    args = ap.parse_args()
    print(json.dumps(evaluate(args.gt, args.pred), indent=2))
    print(json.dumps(measure_validity(args.pred), indent=2))
