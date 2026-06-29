"""Stateful MIDI-to-erhu-position mapping for Erhu Shadow."""

from __future__ import annotations

from dataclasses import dataclass

from note_model import midi_to_name

INNER_BASE_MIDI = 62
OUTER_BASE_MIDI = 69
MAX_POSITION = 18
STRING_CHANGE_PENALTY = 3


@dataclass(frozen=True, slots=True)
class ErhuCandidate:
    string_name: str
    position: int


@dataclass(frozen=True, slots=True)
class ErhuState:
    midi: int
    string_name: str
    position: int
    note_name: str
    confidence: float = 1.0


class ErhuMapper:
    """Choose stable, playable-looking positions without claiming fingering recognition."""

    def __init__(self) -> None:
        self.last_state: ErhuState | None = None

    @staticmethod
    def candidates(midi: int) -> list[ErhuCandidate]:
        result: list[ErhuCandidate] = []
        inner_position = midi - INNER_BASE_MIDI
        outer_position = midi - OUTER_BASE_MIDI
        if 0 <= inner_position <= MAX_POSITION:
            result.append(ErhuCandidate("inner", inner_position))
        if 0 <= outer_position <= MAX_POSITION:
            result.append(ErhuCandidate("outer", outer_position))
        return result

    def map(self, midi: int, confidence: float = 1.0) -> ErhuState | None:
        candidates = self.candidates(midi)
        if not candidates:
            return None
        if self.last_state is None:
            # A lower position is normally more natural. On an exact tie,
            # prefer the outer string for a deterministic initial state.
            chosen = min(
                candidates,
                key=lambda item: (item.position, item.string_name != "outer"),
            )
        else:
            last = self.last_state

            def cost(item: ErhuCandidate) -> tuple[int, int]:
                value = abs(item.position - last.position)
                if item.string_name != last.string_name:
                    value += STRING_CHANGE_PENALTY
                if item.position > 12:
                    value += 1
                # Stable deterministic tie-break: keep the current string.
                return value, item.string_name != last.string_name

            chosen = min(candidates, key=cost)
        state = ErhuState(
            midi=midi,
            string_name=chosen.string_name,
            position=chosen.position,
            note_name=midi_to_name(midi),
            confidence=max(0.0, min(1.0, confidence)),
        )
        self.last_state = state
        return state

    def reset(self) -> None:
        self.last_state = None
