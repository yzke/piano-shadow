import unittest
import random
from unittest.mock import patch

from performance import (
    EAR_TRAINING_LEVELS,
    EarTrainingSession,
    INSTRUMENTS,
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

    def set_program(self, program):
        self.events.append(("program", program))

    def set_pitch_bend_range(self, semitones):
        self.events.append(("bend_range", semitones))

    def pitch_bend(self, value):
        self.events.append(("bend", value))

    def control_change(self, controller, value):
        self.events.append(("cc", controller, value))

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


class FakeSoundFontSynth(FakeSynth):
    def __init__(self, path, program=0):
        super().__init__()
        self.path = path
        self.set_program(program)


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
        self.assertEqual(controller.scale_name, "G 大调 / E 小调")
        self.assertEqual(controller.midi_for_key("Q"), 67)
        self.assertEqual(controller.midi_for_key("Q", 1), 68)
        self.assertEqual(controller.midi_for_key("Q", -1), 66)
        controller.shift_scale(-1)
        self.assertEqual(controller.scale_name, "C 大调 / A 小调")
        controller.shift_scale(-1)
        self.assertEqual(controller.scale_name, "F 大调 / D 小调")

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
        self.assertEqual(len(SCALE_SEQUENCE), 12)
        self.assertEqual(len(set(SCALE_SEQUENCE)), 12)
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

    def test_scale_sequence_follows_the_circle_of_fifths(self):
        controller, _ = self.create_controller()
        names = []
        for _ in SCALE_SEQUENCE:
            names.append(controller.scale_name)
            controller.shift_scale(1)
        self.assertEqual(
            names,
            [
                "C 大调 / A 小调",
                "G 大调 / E 小调",
                "D 大调 / B 小调",
                "A 大调 / F♯ 小调",
                "E 大调 / C♯ 小调",
                "B 大调 / G♯ 小调",
                "F♯ 大调 / D♯ 小调",
                "D♭ 大调 / B♭ 小调",
                "A♭ 大调 / F 小调",
                "E♭ 大调 / C 小调",
                "B♭ 大调 / G 小调",
                "F 大调 / D 小调",
            ],
        )

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

    def test_instrument_navigation_updates_general_midi_program(self):
        controller, _ = self.create_controller()
        self.assertEqual(controller.sound_label, "WIN · 大钢琴")
        self.assertEqual(controller.shift_instrument(1), "电钢琴")
        self.assertEqual(controller.instrument_program, 4)
        self.assertIn(("program", 4), controller.synth.events)
        controller.shift_instrument(-1)
        self.assertEqual(controller.instrument_name, "大钢琴")
        controller.shift_instrument(-1)
        self.assertEqual(
            controller.instrument_name,
            INSTRUMENTS[-1][1],
        )

    def test_soundfont_source_switch_preserves_instrument(self):
        with (
            patch("performance.WinMmPianoSynth", FakeSynth),
            patch("performance.SoundFontSynth", FakeSoundFontSynth),
            patch("performance.MidiInput", FakeMidi),
        ):
            controller = PerformanceController(
                lambda _midi, _velocity: None,
                instrument_index=3,
            )
            self.assertTrue(controller.use_soundfont("test.sf2"))
            self.assertEqual(controller.sound_source, "soundfont")
            self.assertEqual(controller.instrument_program, 16)
            self.assertIn(("program", 16), controller.synth.events)
            self.assertTrue(controller.use_windows())
            self.assertEqual(controller.sound_source, "windows")

    def test_erhu_mode_is_monophonic_and_prepares_alt_glide(self):
        with (
            patch("performance.WinMmPianoSynth", FakeSynth),
            patch("performance.MidiInput", FakeMidi),
        ):
            controller = PerformanceController(
                lambda _midi, _velocity: None,
                instrument_index=len(INSTRUMENTS) - 1,
            )
        self.assertTrue(controller.expressive_strings)
        self.assertEqual(controller.press("Q"), 60)
        self.assertEqual(controller.begin_glide("W"), (60, 62))
        controller.set_pitch_bend(8700)
        controller.finish_glide(60, 62)
        self.assertIn(("bend_range", 12), controller.synth.events)
        self.assertIn(("bend", 8700), controller.synth.events)
        self.assertIn(("off", 60), controller.synth.events)
        self.assertIn(("on", 62, 96), controller.synth.events)

    def test_piano_soft_and_sostenuto_pedals_are_emulated(self):
        controller, _ = self.create_controller()
        controller.set_soft(True)
        controller.press("Q")
        self.assertIn(("on", 60, 61), controller.synth.events)
        controller.set_sostenuto(True)
        controller.release("Q")
        self.assertNotEqual(controller.synth.events[-1], ("off", 60))
        controller.set_sostenuto(False)
        self.assertEqual(controller.synth.events[-1], ("off", 60))
        self.assertIn(("cc", 67, 127), controller.synth.events)
        self.assertIn(("cc", 66, 127), controller.synth.events)

    def test_technique_profiles_cover_instrument_families(self):
        controller, _ = self.create_controller()
        expected = {
            0: "piano",
            16: "organ",
            24: "guitar",
            40: "strings",
            65: "winds",
            80: "synth",
            110: "strings",
        }
        for program, profile in expected.items():
            controller.instrument_index = next(
                index
                for index, (candidate, _name) in enumerate(INSTRUMENTS)
                if candidate == program
            )
            self.assertEqual(controller.technique_profile, profile)

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
            for mode in ("major", "minor"):
                for scale_index in range(len(MAJOR_ROOTS)):
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
