"""Piano note domain model and 88-key mapping utilities."""

from __future__ import annotations

from dataclasses import dataclass

PIANO_LOW = 21
PIANO_HIGH = 108
BLACK_PITCHES = frozenset({1, 3, 6, 8, 10})
NOTE_NAMES = ("C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B")


@dataclass(frozen=True, slots=True)
class NoteEvent:
    midi: int
    start: float
    end: float
    velocity: int = 90
    confidence: float = 1.0

    @property
    def name(self) -> str:
        return midi_to_name(self.midi)


def is_piano_note(midi: int) -> bool:
    return PIANO_LOW <= midi <= PIANO_HIGH


def is_black_key(midi: int) -> bool:
    return midi % 12 in BLACK_PITCHES


def midi_to_name(midi: int) -> str:
    if not 0 <= midi <= 127:
        raise ValueError(f"Invalid MIDI note: {midi}")
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def filter_and_merge(
    notes: list[NoteEvent],
    min_confidence: float,
    min_velocity: int,
    merge_window: float = 0.09,
) -> list[NoteEvent]:
    """Filter weak/out-of-range events and merge near-identical attacks."""
    accepted = [
        n for n in notes
        if is_piano_note(n.midi)
        and n.confidence >= min_confidence
        and n.velocity >= min_velocity
    ]
    accepted.sort(key=lambda n: (n.midi, n.start))
    merged: list[NoteEvent] = []
    for note in accepted:
        if merged and note.midi == merged[-1].midi and note.start - merged[-1].end <= merge_window:
            old = merged[-1]
            merged[-1] = NoteEvent(
                old.midi,
                min(old.start, note.start),
                max(old.end, note.end),
                max(old.velocity, note.velocity),
                max(old.confidence, note.confidence),
            )
        else:
            merged.append(note)
    return sorted(merged, key=lambda n: n.start)


def suppress_weak_harmonics(
    notes: list[NoteEvent],
    strength_ratio: float = 0.62,
    time_window: float = 0.16,
) -> list[NoteEvent]:
    """Remove weak upper partials while preserving deliberate octave chords."""
    harmonic_intervals = frozenset({12, 19, 24, 28, 31, 34, 36})
    result: list[NoteEvent] = []
    for note in notes:
        is_weak_partial = any(
            note.midi - lower.midi in harmonic_intervals
            and abs(note.start - lower.start) <= time_window
            and note.confidence < lower.confidence * strength_ratio
            for lower in notes
            if lower.midi < note.midi
        )
        if not is_weak_partial:
            result.append(note)
    return result
