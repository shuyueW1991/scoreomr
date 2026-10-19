"""Turn a recognized MusicXML score into audible, per-note playback.

The synthesizer is deliberately simple (additive sine + ADSR) so the whole
pipeline stays offline and dependency-light.  It renders *every notehead* as
one MIDI event, which is exactly what "play it note for note" needs; sample
libraries and a real piano sound can be swapped in later without touching the
recognition layer.
"""
from __future__ import annotations

import math
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from music21 import chord, converter, note, tempo, stream


@dataclass
class PlayedNote:
    onset: float       # seconds
    duration: float    # seconds
    midi: int
    velocity: int = 80


def _tempo_bpm(score: stream.Score) -> float:
    marks = score.flatten().getElementsByClass(tempo.MetronomeMark)
    for mark in marks:
        if mark.number:
            return float(mark.number)
    return 100.0


def _iter_noteheads(score: stream.Score):
    for el in score.recurse().notes:
        if isinstance(el, note.Note):
            yield el, [el.pitch.midi]
        elif isinstance(el, chord.Chord):
            yield el, sorted(p.midi for p in el.pitches)


def extract_notes(musicxml: str | Path, expand_repeats: bool = False) -> tuple[list[PlayedNote], float]:
    score = converter.parse(str(musicxml))
    if expand_repeats:
        try:
            score = score.expandRepeats()
        except Exception:
            pass
    bpm = _tempo_bpm(score)
    spb = 60.0 / bpm
    notes: list[PlayedNote] = []
    for el, pitches in _iter_noteheads(score):
        onset = float(el.getOffsetInHierarchy(score)) * spb
        dur = float(el.duration.quarterLength) * spb
        if dur <= 0:  # grace note
            dur = 0.08
        for midi in pitches:
            notes.append(PlayedNote(onset=onset, duration=dur, midi=int(midi)))
    notes.sort(key=lambda n: (n.onset, n.midi))
    return notes, bpm


def synthesize(
    notes: list[PlayedNote],
    out_wav: str | Path,
    sample_rate: int = 44100,
    tail: float = 0.8,
) -> dict:
    if not notes:
        raise ValueError("no notes to synthesize")
    end = max(n.onset + n.duration for n in notes) + tail
    buf = np.zeros(int(end * sample_rate) + 1, dtype=np.float64)

    for n in notes:
        start = int(n.onset * sample_rate)
        length = max(1, int(n.duration * sample_rate))
        t = np.arange(length) / sample_rate
        f0 = 440.0 * 2 ** ((n.midi - 69) / 12.0)
        # A soft piano-ish spectrum; higher partials decay faster.
        wave_data = np.zeros(length, dtype=np.float64)
        for k, amp in enumerate((1.0, 0.45, 0.22, 0.10, 0.05), start=1):
            wave_data += amp * np.sin(2 * np.pi * f0 * k * t)
        # ADSR
        attack = max(1, int(0.008 * sample_rate))
        release = max(1, int(min(0.25, n.duration * 0.5) * sample_rate))
        env = np.ones(length)
        env[:attack] = np.linspace(0, 1, attack)
        env[-release:] *= np.linspace(1, 0, release)
        decay = np.exp(-3.0 * t)
        amp = 0.12 * (n.velocity / 127.0)
        seg = wave_data * env * decay * amp
        buf[start : start + length] += seg[: len(buf) - start]

    peak = float(np.max(np.abs(buf)))
    if peak > 0:
        buf = buf / peak * 0.9
    pcm = (buf * 32767).astype(np.int16)
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_wav), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sample_rate)
        fh.writeframes(pcm.tobytes())
    return {
        "wav": str(out_wav),
        "seconds": round(len(buf) / sample_rate, 3),
        "notes": len(notes),
        "sample_rate": sample_rate,
    }


def write_midi(musicxml: str | Path, out_midi: str | Path) -> str:
    score = converter.parse(str(musicxml))
    out_midi = Path(out_midi)
    out_midi.parent.mkdir(parents=True, exist_ok=True)
    score.write("midi", fp=str(out_midi))
    return str(out_midi)


def piano_roll(notes: list[PlayedNote], out_png: str | Path, title: str = "") -> str:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(14, 4.5), dpi=160)
    for n in notes:
        ax.add_patch(
            plt.Rectangle((n.onset, n.midi - 0.35), n.duration, 0.7, color="#2b6cb0", alpha=0.85)
        )
    ax.set_xlabel("time (s)")
    ax.set_ylabel("MIDI pitch")
    ax.set_title(title or "Recognized score — piano roll")
    ax.grid(alpha=0.2)
    ax.set_xlim(0, max(n.onset + n.duration for n in notes) * 1.02)
    lo = min(n.midi for n in notes) - 2
    hi = max(n.midi for n in notes) + 2
    ax.set_ylim(lo, hi)
    fig.tight_layout()
    fig.savefig(out_png)
    plt.close(fig)
    return str(out_png)


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser()
    ap.add_argument("musicxml")
    ap.add_argument("--wav", default="demo/out/play.wav")
    ap.add_argument("--midi", default="demo/out/play.mid")
    ap.add_argument("--png", default="demo/out/piano_roll.png")
    ap.add_argument("--expand-repeats", action="store_true")
    args = ap.parse_args()
    notes, bpm = extract_notes(args.musicxml, args.expand_repeats)
    info = synthesize(notes, args.wav)
    info["bpm"] = bpm
    info["midi"] = write_midi(args.musicxml, args.midi)
    info["piano_roll"] = piano_roll(notes, args.png, Path(args.musicxml).stem)
    print(json.dumps(info, indent=2))
