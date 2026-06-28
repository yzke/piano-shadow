"""Computer-keyboard and MIDI performance engine."""

from __future__ import annotations

import platform
import random
from collections.abc import Callable


MAJOR_ROOTS = (0, 2, 4, 5, 7, 9, 11)
MAJOR_NAMES = ("C", "D", "E", "F", "G", "A", "B")
MINOR_ROOTS = (9, 11, 0, 2, 4, 5, 7)
MINOR_NAMES = ("A", "B", "C", "D", "E", "F", "G")
MAJOR_INTERVALS = (0, 2, 4, 5, 7, 9, 11)
MINOR_INTERVALS = (0, 2, 3, 5, 7, 8, 10)

KEY_ROWS = (
    (tuple(f"F{index}" for index in range(1, 13)), 36),
    (("1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "="), 48),
    (("Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P", "[", "]"), 60),
    (("A", "S", "D", "F", "G", "H", "J", "K", "L", ";", "'"), 72),
    (("Z", "X", "C", "V", "B", "N", "M", ",", ".", "/"), 84),
)
KEY_BINDINGS = {
    key: (base, degree)
    for keys, base in KEY_ROWS
    for degree, key in enumerate(keys)
}
SCALE_SEQUENCE = tuple(
    (mode, index)
    for index in range(len(MAJOR_ROOTS))
    for mode in ("major", "minor")
)
EAR_TRAINING_LEVELS = (0, 1, 3, 5, 7)


class EarTrainingSession:
    """Generate musical listening exercises and validate ordered answers."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()
        self.note_count = 0
        self.target: tuple[int, ...] = ()
        self.answer: list[int] = []
        self.accepting = False
        self.last_error: tuple[int, int, int] | None = None

    def cycle_level(self) -> int:
        index = EAR_TRAINING_LEVELS.index(self.note_count)
        self.note_count = EAR_TRAINING_LEVELS[
            (index + 1) % len(EAR_TRAINING_LEVELS)
        ]
        self.target = ()
        self.answer.clear()
        self.accepting = False
        self.last_error = None
        return self.note_count

    @staticmethod
    def _scale_pitch(
        base: int, root: int, intervals: tuple[int, ...], degree: int
    ) -> int:
        octave, scale_degree = divmod(degree, 7)
        return base + root + intervals[scale_degree] + octave * 12

    def new_question(
        self, mode: str, scale_index: int
    ) -> tuple[int, ...]:
        if self.note_count == 0:
            self.target = ()
            return self.target
        roots = MAJOR_ROOTS if mode == "major" else MINOR_ROOTS
        intervals = MAJOR_INTERVALS if mode == "major" else MINOR_INTERVALS
        root = roots[scale_index]

        if self.note_count == 1:
            degrees = [self.rng.randrange(7)]
        elif self.note_count == 3:
            # Diatonic triads in root position or inversion, heard as an arpeggio.
            start = self.rng.randrange(7)
            degrees = [start, start + 2, start + 4]
            inversion = self.rng.randrange(3)
            degrees = degrees[inversion:] + [
                degree + 7 for degree in degrees[:inversion]
            ]
        elif self.note_count == 5:
            # Familiar major/minor pentatonic material, with rotation/direction.
            degrees = (
                [0, 1, 2, 4, 5]
                if mode == "major"
                else [0, 2, 3, 4, 6]
            )
            rotation = self.rng.randrange(5)
            degrees = degrees[rotation:] + [
                degree + 7 for degree in degrees[:rotation]
            ]
        else:
            # A complete seven-note mode from a random degree.
            rotation = self.rng.randrange(7)
            degrees = list(range(rotation, rotation + 7))

        # Spread questions across the useful 88-key range while keeping each
        # phrase playable without changing the global octave shift.
        candidates = [
            base
            for base in (36, 48, 60, 72, 84)
            if all(
                21 <= self._scale_pitch(base, root, intervals, degree) <= 108
                for degree in degrees
            )
        ]
        base = self.rng.choice(candidates)
        notes = [
            self._scale_pitch(base, root, intervals, degree)
            for degree in degrees
        ]
        if self.note_count >= 5 and self.rng.choice((False, True)):
            notes.reverse()
        self.target = tuple(notes)
        self.answer.clear()
        self.accepting = False
        self.last_error = None
        return self.target

    def submit(self, midi: int) -> str:
        if not self.accepting or not self.target:
            return "ignored"
        expected = self.target[len(self.answer)]
        if midi != expected:
            self.last_error = (len(self.answer), expected, midi)
            self.answer.clear()
            self.accepting = False
            return "wrong"
        self.answer.append(midi)
        if len(self.answer) == len(self.target):
            self.last_error = None
            self.answer.clear()
            self.accepting = False
            return "correct"
        return "continue"

    def replay(self) -> tuple[int, ...]:
        self.answer.clear()
        self.accepting = False
        self.last_error = None
        return self.target

    def stop(self) -> None:
        self.note_count = 0
        self.target = ()
        self.answer.clear()
        self.accepting = False
        self.last_error = None


class WinMmPianoSynth:
    """Dependency-free Windows General MIDI piano output."""

    def __init__(self) -> None:
        self.available = False
        self._handle = None
        if platform.system() != "Windows":
            return
        try:
            import ctypes
            from ctypes import wintypes

            self._ctypes = ctypes
            self._winmm = ctypes.windll.winmm
            self._handle = wintypes.HANDLE()
            result = self._winmm.midiOutOpen(
                ctypes.byref(self._handle),
                0xFFFFFFFF,  # MIDI_MAPPER
                0,
                0,
                0,
            )
            if result != 0:
                return
            self.available = True
            self._send(0xC0)  # Acoustic Grand Piano, program 0
        except Exception:
            self.available = False

    def _send(self, status: int, data1: int = 0, data2: int = 0) -> None:
        if self.available:
            message = status | ((data1 & 0x7F) << 8) | ((data2 & 0x7F) << 16)
            self._winmm.midiOutShortMsg(self._handle, message)

    def note_on(self, midi: int, velocity: int) -> None:
        self._send(0x90, midi, velocity)

    def note_off(self, midi: int) -> None:
        self._send(0x80, midi, 0)

    def sustain(self, enabled: bool) -> None:
        self._send(0xB0, 64, 127 if enabled else 0)

    def all_notes_off(self) -> None:
        self._send(0xB0, 64, 0)
        self._send(0xB0, 123, 0)
        if self.available:
            self._winmm.midiOutReset(self._handle)

    def close(self) -> None:
        if self.available:
            self.all_notes_off()
            self._winmm.midiOutClose(self._handle)
            self.available = False


class MidiInput:
    """Optional python-rtmidi input adapter."""

    def __init__(
        self,
        note_on: Callable[[int, int], None],
        note_off: Callable[[int], None],
        sustain: Callable[[bool], None],
    ) -> None:
        self.name = "MIDI 未连接"
        self._input = None
        try:
            import rtmidi

            midi_input = rtmidi.MidiIn()
            ports = midi_input.get_ports()
            if not ports:
                return
            midi_input.open_port(0)
            midi_input.set_callback(self._callback)
            self._input = midi_input
            self._note_on = note_on
            self._note_off = note_off
            self._sustain = sustain
            self.name = f"MIDI · {ports[0]}"
        except Exception:
            self._input = None

    def _callback(self, event, _data=None) -> None:
        message, _delta = event
        if not message:
            return
        status = message[0] & 0xF0
        if status == 0x90 and len(message) >= 3 and message[2] > 0:
            self._note_on(int(message[1]), int(message[2]))
        elif status in (0x80, 0x90) and len(message) >= 2:
            self._note_off(int(message[1]))
        elif (
            status == 0xB0
            and len(message) >= 3
            and int(message[1]) == 64
        ):
            self._sustain(int(message[2]) >= 64)

    def close(self) -> None:
        if self._input is not None:
            self._input.close_port()
            self._input = None


class PerformanceController:
    def __init__(
        self,
        visual_note: Callable[[int, int], None],
        played_note: Callable[[int], None] | None = None,
    ) -> None:
        self.visual_note = visual_note
        self.played_note = played_note or (lambda _midi: None)
        self.synth = WinMmPianoSynth()
        self.mode = "major"
        self.scale_index = 0
        self.octave_shift = 0
        self.sustain_enabled = False
        self.resting = False
        self.input_mode = "keyboard"
        self.pressed: dict[str, int] = {}
        self.ear_training = EarTrainingSession()
        self.midi = MidiInput(
            self._midi_note_on,
            self._midi_note_off,
            self._midi_sustain,
        )

    @property
    def scale_name(self) -> str:
        names = MAJOR_NAMES if self.mode == "major" else MINOR_NAMES
        return f"{names[self.scale_index]} {'大调' if self.mode == 'major' else '小调'}"

    @property
    def scale_notes(self) -> tuple[int, ...]:
        roots = MAJOR_ROOTS if self.mode == "major" else MINOR_ROOTS
        intervals = MAJOR_INTERVALS if self.mode == "major" else MINOR_INTERVALS
        return tuple((roots[self.scale_index] + value) % 12 for value in intervals)

    def reset(self) -> None:
        self.all_notes_off()
        self.mode = "major"
        self.scale_index = 0
        self.octave_shift = 0
        self.resting = False
        self.input_mode = "keyboard"
        self.ear_training.stop()

    def midi_for_key(self, key: str, accidental: int = 0) -> int | None:
        binding = KEY_BINDINGS.get(key)
        if binding is None:
            return None
        base, degree = binding
        roots = MAJOR_ROOTS if self.mode == "major" else MINOR_ROOTS
        intervals = MAJOR_INTERVALS if self.mode == "major" else MINOR_INTERVALS
        octave, scale_degree = divmod(degree, 7)
        midi = (
            base
            + roots[self.scale_index]
            + intervals[scale_degree]
            + octave * 12
            + self.octave_shift * 12
            + accidental
        )
        return midi if 21 <= midi <= 108 else None

    def press(self, key: str, accidental: int = 0, velocity: int = 96) -> int | None:
        if self.input_mode != "keyboard" or self.resting or key in self.pressed:
            return None
        midi = self.midi_for_key(key, accidental)
        if midi is None:
            return None
        self.pressed[key] = midi
        self.synth.note_on(midi, velocity)
        self.visual_note(midi, velocity)
        self.played_note(midi)
        return midi

    def release(self, key: str) -> None:
        midi = self.pressed.pop(key, None)
        if midi is not None:
            self.synth.note_off(midi)

    def set_sustain(self, enabled: bool) -> None:
        self.sustain_enabled = enabled
        self.synth.sustain(enabled)

    def set_rest(self, enabled: bool) -> None:
        self.resting = enabled
        if enabled:
            self.all_notes_off()

    def all_notes_off(self) -> None:
        self.pressed.clear()
        self.sustain_enabled = False
        self.synth.all_notes_off()

    def shift_octave(self, amount: int) -> None:
        self.all_notes_off()
        self.octave_shift = max(-1, min(1, self.octave_shift + amount))

    def shift_scale(self, amount: int) -> None:
        """Move in one predictable sequence containing both major and minor keys."""
        self.all_notes_off()
        current = SCALE_SEQUENCE.index((self.mode, self.scale_index))
        self.mode, self.scale_index = SCALE_SEQUENCE[
            (current + amount) % len(SCALE_SEQUENCE)
        ]

    def toggle_input_mode(self) -> str:
        self.all_notes_off()
        self.input_mode = "midi" if self.input_mode == "keyboard" else "keyboard"
        return self.input_mode

    def _midi_note_on(self, midi: int, velocity: int) -> None:
        if (
            self.input_mode == "midi"
            and not self.resting
            and 21 <= midi <= 108
        ):
            self.synth.note_on(midi, velocity)
            self.visual_note(midi, velocity)
            self.played_note(midi)

    def _midi_note_off(self, midi: int) -> None:
        if self.input_mode == "midi":
            self.synth.note_off(midi)

    def _midi_sustain(self, enabled: bool) -> None:
        if self.input_mode == "midi":
            self.set_sustain(enabled)

    def close(self) -> None:
        self.ear_training.stop()
        self.midi.close()
        self.synth.close()
