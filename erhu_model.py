"""Stateful MIDI-to-erhu-position mapping for Erhu Shadow."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from statistics import median

from note_model import midi_to_name

INNER_BASE_MIDI = 62
OUTER_BASE_MIDI = 69
MAX_POSITION = 18
SWITCH_PENALTY = 8.0
SWITCH_CONFIRM_FRAMES = 6
MIN_SWITCH_INTERVAL_SECONDS = 0.180
OPEN_STRING_BONUS = -1.5
HIGH_POSITION_PENALTY_START = 12.0
DEAD_ZONE = 0.25
EMA_ALPHA = 0.25
MEDIAN_WINDOW = 5
MIN_SWITCH_CONFIDENCE = 0.42
KEY_MODE_ROOTS = {
    "auto": 2,
    "D": 2,
    "G": 7,
    "F": 5,
    "Bb": 10,
    "C": 0,
    "A": 9,
}
JIANPU_BY_MAJOR_DEGREE = {
    0: "1",
    1: "♯1",
    2: "2",
    3: "♯2",
    4: "3",
    5: "4",
    6: "♯4",
    7: "5",
    8: "♯5",
    9: "6",
    10: "♭7",
    11: "7",
}


class ErhuKeyMode(str, Enum):
    AUTO = "auto"
    D = "D"
    G = "G"
    F = "F"
    BB = "Bb"
    C = "C"
    A = "A"


def normalize_key_mode(value: str | ErhuKeyMode) -> ErhuKeyMode:
    raw = value.value if isinstance(value, ErhuKeyMode) else str(value)
    for mode in ErhuKeyMode:
        if mode.value == raw:
            return mode
    return ErhuKeyMode.AUTO


def erhu_jianpu(midi: int, key_mode: str | ErhuKeyMode = ErhuKeyMode.AUTO) -> str:
    mode = normalize_key_mode(key_mode)
    root = KEY_MODE_ROOTS[mode.value]
    return JIANPU_BY_MAJOR_DEGREE[(midi % 12 - root) % 12]


@dataclass(frozen=True, slots=True)
class ErhuCandidate:
    string_name: str
    position: float


@dataclass(frozen=True, slots=True)
class ErhuState:
    midi: int
    midi_float: float
    raw_midi: float
    string_name: str
    position: float
    note_name: str
    confidence: float = 1.0
    switch_reason: str = "init"


class ErhuMapper:
    """Choose stable, playable-looking positions without claiming fingering recognition."""

    def __init__(self) -> None:
        self.last_state: ErhuState | None = None
        self.last_switch_time = -1e9
        self._pending_string: str | None = None
        self._pending_frames = 0
        self._raw_window: list[float] = []
        self._smoothed_midi: float | None = None

    @staticmethod
    def candidates(midi: float) -> list[ErhuCandidate]:
        result: list[ErhuCandidate] = []
        inner_position = midi - INNER_BASE_MIDI
        outer_position = midi - OUTER_BASE_MIDI
        if 0 <= inner_position <= MAX_POSITION:
            result.append(ErhuCandidate("inner", inner_position))
        if 0 <= outer_position <= MAX_POSITION:
            result.append(ErhuCandidate("outer", outer_position))
        return result

    def map(
        self,
        midi: float,
        confidence: float = 1.0,
        timestamp: float | None = None,
        smooth: bool = True,
    ) -> ErhuState | None:
        raw_midi = float(midi)
        confidence = max(0.0, min(1.0, confidence))
        if confidence < MIN_SWITCH_CONFIDENCE:
            return self.last_state
        midi_float = self._smooth_midi(raw_midi) if smooth else raw_midi
        rounded_midi = round(midi_float)
        candidates = self.candidates(midi_float)
        if not candidates:
            self._pending_string = None
            self._pending_frames = 0
            return None
        now = 0.0 if timestamp is None else float(timestamp)
        if self.last_state is None:
            # A lower position is normally more natural. On an exact tie,
            # prefer the outer string for a deterministic initial state.
            chosen = min(
                candidates,
                key=lambda item: (
                    self._position_cost(item),
                    item.string_name != "outer",
                ),
            )
            switch_reason = "init"
            self.last_switch_time = now
        else:
            last = self.last_state
            current = next(
                (
                    item
                    for item in candidates
                    if item.string_name == last.string_name
                ),
                None,
            )
            if current is None:
                chosen = min(candidates, key=self._position_cost)
                switch_reason = "current_unplayable"
                if chosen.string_name != last.string_name:
                    self.last_switch_time = now
                self._pending_string = None
                self._pending_frames = 0
            else:
                best = min(candidates, key=self._position_cost)
                current_cost = self._position_cost(current)
                best_cost = self._position_cost(best)
                if best.string_name != last.string_name:
                    best_cost += SWITCH_PENALTY
                improvement = current_cost - best_cost
                can_switch_by_time = (
                    now - self.last_switch_time >= MIN_SWITCH_INTERVAL_SECONDS
                )
                if (
                    best.string_name != last.string_name
                    and improvement > DEAD_ZONE
                    and confidence >= MIN_SWITCH_CONFIDENCE
                    and can_switch_by_time
                ):
                    if self._pending_string == best.string_name:
                        self._pending_frames += 1
                    else:
                        self._pending_string = best.string_name
                        self._pending_frames = 1
                    if self._pending_frames >= SWITCH_CONFIRM_FRAMES:
                        chosen = best
                        switch_reason = "confirmed_better_string"
                        self.last_switch_time = now
                        self._pending_string = None
                        self._pending_frames = 0
                    else:
                        chosen = current
                        switch_reason = "hold_confirming"
                else:
                    chosen = current
                    switch_reason = "hold_current"
                    if best.string_name == last.string_name or improvement <= DEAD_ZONE:
                        self._pending_string = None
                        self._pending_frames = 0

        state = ErhuState(
            midi=rounded_midi,
            midi_float=midi_float,
            raw_midi=raw_midi,
            string_name=chosen.string_name,
            position=chosen.position,
            note_name=midi_to_name(rounded_midi),
            confidence=confidence,
            switch_reason=switch_reason,
        )
        self.last_state = state
        return state

    def _smooth_midi(self, raw_midi: float) -> float:
        self._raw_window.append(raw_midi)
        self._raw_window = self._raw_window[-MEDIAN_WINDOW:]
        filtered = float(median(self._raw_window))
        if self._smoothed_midi is None:
            self._smoothed_midi = filtered
        else:
            self._smoothed_midi = (
                self._smoothed_midi * (1.0 - EMA_ALPHA) + filtered * EMA_ALPHA
            )
        return self._smoothed_midi

    @staticmethod
    def _position_cost(item: ErhuCandidate) -> float:
        cost = item.position
        if abs(item.position) <= DEAD_ZONE:
            cost += OPEN_STRING_BONUS
        if item.position > HIGH_POSITION_PENALTY_START:
            cost += item.position - HIGH_POSITION_PENALTY_START
        return cost

    def reset(self) -> None:
        self.last_state = None
        self.last_switch_time = -1e9
        self._pending_string = None
        self._pending_frames = 0
        self._raw_window.clear()
        self._smoothed_midi = None


class ErhuStateMachine(ErhuMapper):
    """Explicit state-machine name for stable erhu string selection."""
