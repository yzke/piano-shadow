import unittest
from unittest.mock import patch

from performance import PerformanceController


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

    def test_default_five_rows_and_octave_shift(self):
        controller, _ = self.create_controller()
        self.assertEqual(controller.midi_for_key("F1"), 36)
        self.assertEqual(controller.midi_for_key("1"), 48)
        self.assertEqual(controller.midi_for_key("Q"), 60)
        self.assertEqual(controller.midi_for_key("A"), 72)
        self.assertEqual(controller.midi_for_key("Z"), 84)
        controller.shift_octave(1)
        self.assertEqual(controller.midi_for_key("1"), 60)

    def test_major_minor_and_accidentals(self):
        controller, _ = self.create_controller()
        controller.next_major()
        self.assertEqual(controller.scale_name, "D 大调")
        self.assertEqual(controller.midi_for_key("Q"), 62)
        self.assertEqual(controller.midi_for_key("U"), 73)
        self.assertEqual(controller.midi_for_key("Q", 1), 63)
        self.assertEqual(controller.midi_for_key("Q", -1), 61)
        controller.next_minor()
        self.assertEqual(controller.scale_name, "B 小调")
        self.assertEqual(controller.midi_for_key("Q"), 71)

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


if __name__ == "__main__":
    unittest.main()
