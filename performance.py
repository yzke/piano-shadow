"""Computer-keyboard and MIDI performance engine."""

from __future__ import annotations

import platform
import random
from collections.abc import Callable
from pathlib import Path


# Clockwise circle of fifths. Relative major/minor keys share each index so
# the unified scale sequence can keep related tonalities next to each other.
MAJOR_ROOTS = (0, 7, 2, 9, 4, 11, 6, 1, 8, 3, 10, 5)
MAJOR_NAMES = ("C", "G", "D", "A", "E", "B", "F♯", "D♭", "A♭", "E♭", "B♭", "F")
MINOR_ROOTS = (9, 4, 11, 6, 1, 8, 3, 10, 5, 0, 7, 2)
MINOR_NAMES = ("A", "E", "B", "F♯", "C♯", "G♯", "D♯", "B♭", "F", "C", "G", "D")
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
    ("major", index)
    for index in range(len(MAJOR_ROOTS))
)
EAR_TRAINING_LEVELS = (0, 1, 3, 5, 7)
INSTRUMENTS = (
    (0, "大钢琴"),
    (4, "电钢琴"),
    (6, "羽管键琴"),
    (16, "风琴"),
    (19, "教堂风琴"),
    (24, "尼龙吉他"),
    (25, "钢弦吉他"),
    (27, "清音电吉他"),
    (32, "原声贝斯"),
    (33, "指弹贝斯"),
    (40, "小提琴"),
    (42, "大提琴"),
    (48, "弦乐合奏"),
    (56, "小号"),
    (61, "铜管合奏"),
    (65, "中音萨克斯"),
    (73, "长笛"),
    (80, "方波合成器"),
    (88, "幻想音色"),
)


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
    """Dependency-free Windows General MIDI output."""

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
            self.set_program(0)
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

    def set_program(self, program: int) -> None:
        self._send(0xC0, program)

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


class SoundFontSynth:
    """Optional self-contained SoundFont output using TinySoundFont."""

    def __init__(self, path: Path, program: int = 0) -> None:
        self.available = False
        self._synth = None
        try:
            import tinysoundfont

            synth = tinysoundfont.Synth()
            self._synth = synth
            soundfont_id = synth.sfload(str(path))
            synth.program_select(0, soundfont_id, 0, program)
            synth.start()
            self._soundfont_id = soundfont_id
            self.available = True
        except Exception:
            self.close()

    def note_on(self, midi: int, velocity: int) -> None:
        if self.available:
            self._synth.noteon(0, midi, velocity)

    def note_off(self, midi: int) -> None:
        if self.available:
            self._synth.noteoff(0, midi)

    def set_program(self, program: int) -> None:
        if self.available:
            self.all_notes_off()
            self._synth.program_select(
                0, self._soundfont_id, 0, max(0, min(127, program))
            )

    def sustain(self, enabled: bool) -> None:
        if self.available:
            self._synth.control_change(0, 64, 127 if enabled else 0)

    def all_notes_off(self) -> None:
        if self.available:
            self._synth.control_change(0, 64, 0)
            self._synth.notes_off(0)

    def close(self) -> None:
        synth = self._synth
        self._synth = None
        self.available = False
        if synth is not None:
            try:
                synth.sounds_off()
                synth.stop()
            except Exception:
                pass


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
        sound_source: str = "windows",
        instrument_index: int = 0,
        soundfont_path: Path | None = None,
    ) -> None:
        self.visual_note = visual_note
        self.played_note = played_note or (lambda _midi: None)
        self.instrument_index = max(
            0, min(len(INSTRUMENTS) - 1, instrument_index)
        )
        self.sound_source = "windows"
        self.synth = WinMmPianoSynth()
        self.synth.set_program(self.instrument_program)
        if sound_source == "soundfont" and soundfont_path is not None:
            self.use_soundfont(soundfont_path)
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
        return (
            f"{MAJOR_NAMES[self.scale_index]} 大调 / "
            f"{MINOR_NAMES[self.scale_index]} 小调"
        )

    @property
    def instrument_program(self) -> int:
        return INSTRUMENTS[self.instrument_index][0]

    @property
    def instrument_name(self) -> str:
        return INSTRUMENTS[self.instrument_index][1]

    @property
    def sound_label(self) -> str:
        source = "SF2" if self.sound_source == "soundfont" else "WIN"
        return f"{source} · {self.instrument_name}"

    def shift_instrument(self, amount: int) -> str:
        self.all_notes_off()
        self.instrument_index = (
            self.instrument_index + amount
        ) % len(INSTRUMENTS)
        self.synth.set_program(self.instrument_program)
        return self.instrument_name

    def use_windows(self) -> bool:
        if self.sound_source == "windows":
            self.all_notes_off()
            self.synth.set_program(self.instrument_program)
            return self.synth.available
        replacement = WinMmPianoSynth()
        if not replacement.available:
            replacement.close()
            return False
        replacement.set_program(self.instrument_program)
        old = self.synth
        self.synth = replacement
        self.sound_source = "windows"
        old.close()
        return True

    def use_soundfont(self, path: Path) -> bool:
        replacement = SoundFontSynth(path, self.instrument_program)
        if not replacement.available:
            replacement.close()
            return False
        old = self.synth
        self.synth = replacement
        self.sound_source = "soundfont"
        old.close()
        return True

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
        """Move through relative major/minor pairs on the circle of fifths."""
        self.all_notes_off()
        self.mode = "major"
        self.scale_index = (
            self.scale_index + amount
        ) % len(MAJOR_ROOTS)

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
