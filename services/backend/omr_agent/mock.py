"""Deterministic demo score used only when OMR_MOCK=1 (never in production)."""
from __future__ import annotations

from pathlib import Path


def write_demo_score(path: str | Path) -> str:
    from music21 import chord, clef, key, meter, note, stream, tempo

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    score = stream.Score()
    score.metadata = None
    part = stream.Part(id="P1")
    part.append(clef.TrebleClef())
    part.append(key.Key("C"))
    part.append(meter.TimeSignature("4/4"))
    part.append(tempo.MetronomeMark(number=96))

    melody = [
        ["C4", "E4", "G4", "E4"],
        ["F4", "A4", "C5", "A4"],
        ["G4", "B4", "D5", "B4"],
        ["C5", "G4", "E4", "C4"],
        ["C4", "D4", "E4", "F4"],
        ["G4", "A4", "B4", "C5"],
        ["C5", "B4", "A4", "G4"],
        ["F4", "E4", "D4", "C4"],
    ]
    for index, bar in enumerate(melody, start=1):
        measure = stream.Measure(number=index)
        for pitch_name in bar:
            n = note.Note(pitch_name)
            n.quarterLength = 1.0
            measure.append(n)
        part.append(measure)

    # One chord and one half note so the result exercises polyphony/durations.
    bridge = stream.Measure(number=9)
    bridge.append(chord.Chord(["C4", "E4", "G4"], quarterLength=2.0))
    bridge.append(chord.Chord(["G3", "B3", "D4"], quarterLength=2.0))
    part.append(bridge)
    score.insert(0, part)
    score.write("musicxml", fp=str(path))
    return str(path)
