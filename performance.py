"""Computer-keyboard and MIDI performance engine."""

from __future__ import annotations

import platform
from collections.abc import Callable


MAJOR_ROOTS = (0, 2, 4, 5, 7, 9, 11)
MAJOR_NAMES = ("C", "D", "E", "F", "G", "A", "B")
MINOR_ROOTS = (9, 11, 0, 2, 4, 5, 7)
MINOR_NAMES = ("A", "B", "C", "D", "E", "F", "G")
MAJOR_INTERVALS = (0, 2, 4, 5, 7, 9, 11)
MINOR_INTERVALS = (0, 2, 3, 5, 7, 8, 10)

KEY_ROWS = (
    (("F1", "F2", "F3", "F4", "F5", "F6", "F7"), 36),
    (("1", "2", "3", "4", "5", "6", "7"), 48),
    (("Q", "W", "E", "R", "T", "Y", "U"), 60),
    (("A", "S", "D", "F", "G", "H", "J"), 72),
    (("Z", "X", "C", "V", "B", "N", "M"), 84),
)
KEY_BINDINGS = {
    key: (base, degree)
    for keys, base in KEY_ROWS
    for degree, key in enumerate(keys)
}


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
    def __init__(self, visual_note: Callable[[int, int], None]) -> None:
        self.visual_note = visual_note
        self.synth = WinMmPianoSynth()
        self.mode = "major"
        self.scale_index = 0
        self.octave_shift = 0
        self.sustain_enabled = False
        self.resting = False
        self.input_mode = "keyboard"
        self.pressed: dict[str, int] = {}
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

    def midi_for_key(self, key: str, accidental: int = 0) -> int | None:
        binding = KEY_BINDINGS.get(key)
        if binding is None:
            return None
        base, degree = binding
        roots = MAJOR_ROOTS if self.mode == "major" else MINOR_ROOTS
        intervals = MAJOR_INTERVALS if self.mode == "major" else MINOR_INTERVALS
        midi = (
            base
            + roots[self.scale_index]
            + intervals[degree]
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

    def next_major(self) -> None:
        self.all_notes_off()
        if self.mode == "major":
            self.scale_index = (self.scale_index + 1) % len(MAJOR_ROOTS)
        self.mode = "major"

    def next_minor(self) -> None:
        self.all_notes_off()
        if self.mode == "minor":
            self.scale_index = (self.scale_index + 1) % len(MINOR_ROOTS)
        self.mode = "minor"

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

    def _midi_note_off(self, midi: int) -> None:
        if self.input_mode == "midi":
            self.synth.note_off(midi)

    def _midi_sustain(self, enabled: bool) -> None:
        if self.input_mode == "midi":
            self.set_sustain(enabled)

    def close(self) -> None:
        self.midi.close()
        self.synth.close()
