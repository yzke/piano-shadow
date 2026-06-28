import unittest
import random
from unittest.mock import patch

from performance import (
    EAR_TRAINING_LEVELS,
    EarTrainingSession,
    KEY_ROWS,
    MAJOR_INTERVALS,
    MAJOR_ROOTS,
    MINOR_INTERVALS,
    MINOR_ROOTS,
    SCALE_SEQUENCE,
    PerformanceController,
)


class FakeSynth:
    def __init__(self):
        self.available = True
        self.events = []

    def note_on(self, midi, velocity):
        self.events.append(("on", midi, velocity))

    def note_off(self, midi):
        self.events.append(("off", midi))

    def sustain(self, enabled):
        self.events.append(("sustain", enabled))

    def all_notes_off(self):
        self.events.append(("all_off",))

    def close(self):
        pass


class FakeMidi:
    def __init__(self, *_args):
        self.name = "MIDI 未连接"

    def close(self):
        pass


class PerformanceTests(unittest.TestCase):
    def create_controller(self):
        visual = []
        with (
            patch("performance.WinMmPianoSynth", FakeSynth),
            patch("performance.MidiInput", FakeMidi),
        ):
            controller = PerformanceController(
                lambda midi, velocity: visual.append((midi, velocity))
            )
        return controller, visual

    def test_rows_continue_into_the_next_octave(self):
        controller, _ = self.create_controller()
        self.assertEqual(controller.midi_for_key("F1"), 36)
        self.assertEqual(controller.midi_for_key("F8"), 48)
        self.assertEqual(controller.midi_for_key("1"), 48)
        self.assertEqual(controller.midi_for_key("8"), 60)
        self.assertEqual(controller.midi_for_key("="), 67)
        self.assertEqual(controller.midi_for_key("Q"), 60)
        self.assertEqual(controller.midi_for_key("I"), 72)
        self.assertEqual(controller.midi_for_key("A"), 72)
        self.assertEqual(controller.midi_for_key("K"), 84)
        self.assertEqual(controller.midi_for_key("Z"), 84)
        self.assertEqual(controller.midi_for_key(","), 96)
        controller.shift_octave(1)
        self.assertEqual(controller.midi_for_key("1"), 60)

    def test_scale_sequence_moves_both_directions(self):
        controller, _ = self.create_controller()
        controller.shift_scale(1)
        self.assertEqual(controller.scale_name, "A 小调")
        controller.shift_scale(1)
        self.assertEqual(controller.scale_name, "D 大调")
        self.assertEqual(controller.midi_for_key("Q"), 62)
        self.assertEqual(controller.midi_for_key("Q", 1), 63)
        self.assertEqual(controller.midi_for_key("Q", -1), 61)
        controller.shift_scale(-1)
        self.assertEqual(controller.scale_name, "A 小调")
        controller.shift_scale(-1)
        self.assertEqual(controller.scale_name, "C 大调")
        controller.shift_scale(-1)
        self.assertEqual(controller.scale_name, "G 小调")

    def test_every_extended_key_is_correct_in_every_scale(self):
        controller, _ = self.create_controller()
        for mode, scale_index in SCALE_SEQUENCE:
            controller.mode = mode
            controller.scale_index = scale_index
            roots = MAJOR_ROOTS if mode == "major" else MINOR_ROOTS
            intervals = MAJOR_INTERVALS if mode == "major" else MINOR_INTERVALS
            for keys, base in KEY_ROWS:
                for degree, key in enumerate(keys):
                    octave, scale_degree = divmod(degree, 7)
                    expected = (
                        base
                        + roots[scale_index]
                        + intervals[scale_degree]
                        + octave * 12
                    )
                    self.assertEqual(
                        controller.midi_for_key(key),
                        expected if 21 <= expected <= 108 else None,
                        f"{mode=} {scale_index=} {key=}",
                    )

    def test_scale_sequence_is_complete_and_reversible(self):
        controller, _ = self.create_controller()
        self.assertEqual(len(SCALE_SEQUENCE), 14)
        self.assertEqual(len(set(SCALE_SEQUENCE)), 14)
        visited = []
        for _ in SCALE_SEQUENCE:
            visited.append((controller.mode, controller.scale_index))
            controller.shift_scale(1)
        self.assertEqual(visited, list(SCALE_SEQUENCE))
        self.assertEqual((controller.mode, controller.scale_index), SCALE_SEQUENCE[0])

        for _ in SCALE_SEQUENCE:
            before = (controller.mode, controller.scale_index)
            controller.shift_scale(1)
            controller.shift_scale(-1)
            self.assertEqual((controller.mode, controller.scale_index), before)

    def test_sustain_rest_and_note_lifecycle(self):
        controller, visual = self.create_controller()
        self.assertEqual(controller.press("Q"), 60)
        self.assertEqual(visual, [(60, 96)])
        controller.release("Q")
        controller.set_sustain(True)
        controller.set_rest(True)
        self.assertTrue(controller.resting)
        self.assertIsNone(controller.press("W"))
        controller.set_rest(False)
        self.assertEqual(controller.press("W"), 62)
        self.assertIn(("sustain", True), controller.synth.events)
        self.assertIn(("all_off",), controller.synth.events)

    def test_keyboard_and_midi_modes_are_exclusive(self):
        controller, _ = self.create_controller()
        self.assertEqual(controller.input_mode, "keyboard")
        self.assertEqual(controller.toggle_input_mode(), "midi")
        self.assertIsNone(controller.press("Q"))
        controller._midi_note_on(64, 88)
        self.assertIn(("on", 64, 88), controller.synth.events)
        self.assertEqual(controller.toggle_input_mode(), "keyboard")
        controller._midi_note_on(67, 88)
        self.assertNotIn(("on", 67, 88), controller.synth.events)

    def test_ear_training_cycles_all_levels_and_closes(self):
        session = EarTrainingSession(random.Random(4))
        levels = [session.cycle_level() for _ in range(5)]
        self.assertEqual(levels, [1, 3, 5, 7, 0])
        self.assertEqual(tuple(EAR_TRAINING_LEVELS), (0, 1, 3, 5, 7))

    def test_ear_training_generates_every_scale_and_level(self):
        session = EarTrainingSession(random.Random(19))
        observed = set()
        for level in (1, 3, 5, 7):
            session.note_count = level
            for mode, scale_index in SCALE_SEQUENCE:
                roots = MAJOR_ROOTS if mode == "major" else MINOR_ROOTS
                intervals = MAJOR_INTERVALS if mode == "major" else MINOR_INTERVALS
                allowed_pitch_classes = {
                    (roots[scale_index] + interval) % 12
                    for interval in intervals
                }
                for _ in range(25):
                    target = session.new_question(mode, scale_index)
                    self.assertEqual(len(target), level)
                    self.assertTrue(all(21 <= midi <= 108 for midi in target))
                    self.assertTrue(
                        all(midi % 12 in allowed_pitch_classes for midi in target)
                    )
                    observed.update(target)
        self.assertLess(min(observed), 48)
        self.assertGreater(max(observed), 96)
        self.assertGreater(len(observed), 45)

    def test_ear_training_requires_the_ordered_complete_answer(self):
        session = EarTrainingSession(random.Random(2))
        session.note_count = 3
        target = session.new_question("major", 0)
        session.accepting = True
        self.assertEqual(session.submit(target[0]), "continue")
        self.assertEqual(session.submit(target[1]), "continue")
        self.assertEqual(session.submit(target[2]), "correct")
        self.assertFalse(session.accepting)

        session.replay()
        session.accepting = True
        wrong = target[0] + 1
        self.assertEqual(session.submit(wrong), "wrong")
        self.assertEqual(session.last_error, (0, target[0], wrong))
        self.assertEqual(session.answer, [])
        self.assertFalse(session.accepting)

    def test_controller_reports_keyboard_and_midi_answers(self):
        played = []
        with (
            patch("performance.WinMmPianoSynth", FakeSynth),
            patch("performance.MidiInput", FakeMidi),
        ):
            controller = PerformanceController(
                lambda _midi, _velocity: None,
                played.append,
            )
        self.assertEqual(controller.press("Q"), 60)
        controller.release("Q")
        controller.toggle_input_mode()
        controller._midi_note_on(64, 90)
        self.assertEqual(played, [60, 64])


if __name__ == "__main__":
    unittest.main()
