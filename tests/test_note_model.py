import unittest

from config import parse_args
from note_model import (
    NoteEvent,
    filter_and_merge,
    is_black_key,
    midi_to_name,
    suppress_weak_harmonics,
)


class NoteModelTests(unittest.TestCase):
    def test_gpu_is_default_model(self):
        self.assertEqual(parse_args([]).model, "piano-gpu")

    def test_piano_boundaries_and_middle_c(self):
        self.assertEqual(midi_to_name(21), "A0")
        self.assertEqual(midi_to_name(60), "C4")
        self.assertEqual(midi_to_name(108), "C8")

    def test_standard_keyboard_has_52_white_and_36_black_keys(self):
        notes = range(21, 109)
        self.assertEqual(sum(not is_black_key(note) for note in notes), 52)
        self.assertEqual(sum(is_black_key(note) for note in notes), 36)

    def test_filter_and_merge(self):
        notes = [
            NoteEvent(60, 0.0, 0.20, 80, 0.8),
            NoteEvent(60, 0.25, 0.45, 95, 0.9),
            NoteEvent(61, 0.1, 0.20, 10, 0.9),
            NoteEvent(10, 0.0, 1.0, 127, 1.0),
        ]
        merged = filter_and_merge(notes, min_confidence=0.35, min_velocity=24)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].midi, 60)
        self.assertEqual(merged[0].end, 0.45)
        self.assertEqual(merged[0].velocity, 95)

    def test_weak_harmonic_is_removed_but_strong_octave_is_kept(self):
        fundamental = NoteEvent(48, 0.0, 0.4, 110, 0.9)
        weak_partial = NoteEvent(72, 0.02, 0.3, 42, 0.4)
        strong_octave = NoteEvent(60, 0.01, 0.4, 100, 0.8)
        result = suppress_weak_harmonics([fundamental, weak_partial, strong_octave])
        self.assertEqual([note.midi for note in result], [48, 60])


if __name__ == "__main__":
    unittest.main()
