import unittest

from erhu_model import ErhuMapper, ErhuStateMachine, erhu_jianpu


class ErhuMapperTests(unittest.TestCase):
    def test_candidate_ranges_and_open_strings(self):
        mapper = ErhuMapper()
        self.assertEqual(
            [(item.string_name, item.position) for item in mapper.candidates(62)],
            [("inner", 0)],
        )
        self.assertEqual(
            [(item.string_name, item.position) for item in mapper.candidates(69)],
            [("inner", 7), ("outer", 0)],
        )
        self.assertEqual(
            [(item.string_name, item.position) for item in mapper.candidates(80)],
            [("inner", 18), ("outer", 11)],
        )
        self.assertEqual(mapper.candidates(61), [])
        self.assertEqual(mapper.candidates(88), [])

    def test_first_state_prefers_lower_position(self):
        state = ErhuMapper().map(69, 0.8)
        self.assertIsNotNone(state)
        self.assertEqual((state.string_name, state.position), ("outer", 0))
        self.assertEqual(state.note_name, "A4")
        self.assertEqual(state.confidence, 0.8)

    def test_overlap_keeps_previous_string_when_cost_is_lower(self):
        mapper = ErhuMapper()
        first = mapper.map(67)
        second = mapper.map(69)
        third = mapper.map(71)
        self.assertEqual(first.string_name, "inner")
        self.assertEqual(second.string_name, "inner")
        self.assertEqual(third.string_name, "inner")
        self.assertGreater(third.position, second.position)

    def test_state_switches_when_current_string_is_unplayable(self):
        mapper = ErhuMapper()
        mapper.map(62, timestamp=0.0)
        state = None
        for frame in range(20):
            state = mapper.map(82, timestamp=0.3 + frame * 0.04)
        self.assertEqual(state.string_name, "outer")

    def test_a4_does_not_bounce_between_strings(self):
        mapper = ErhuStateMachine()
        states = [
            mapper.map(69 + jitter, confidence=0.9, timestamp=index * 0.03)
            for index, jitter in enumerate((0.0, 0.05, -0.04, 0.03, -0.02, 0.01))
        ]
        self.assertTrue(all(state is not None for state in states))
        self.assertEqual({state.string_name for state in states if state}, {"outer"})

    def test_open_string_candidate_tolerates_slightly_flat_pitch(self):
        mapper = ErhuMapper()
        candidates = mapper.candidates(68.9)
        self.assertEqual([item.string_name for item in candidates], ["inner", "outer"])
        self.assertAlmostEqual(candidates[0].position, 6.9)
        self.assertEqual(candidates[1].position, 0.0)
        state = mapper.map(68.9, confidence=0.9, smooth=False)
        self.assertEqual((state.string_name, state.position), ("outer", 0.0))

    def test_open_string_switch_confirms_quickly(self):
        mapper = ErhuMapper()
        mapper.map(67, confidence=0.9, timestamp=0.0, smooth=False)
        first = mapper.map(69, confidence=0.9, timestamp=0.30, smooth=False)
        second = mapper.map(69, confidence=0.9, timestamp=0.34, smooth=False)
        self.assertEqual(first.string_name, "inner")
        self.assertEqual((second.string_name, second.position), ("outer", 0.0))

    def test_low_confidence_does_not_update_target(self):
        mapper = ErhuMapper()
        self.assertIsNone(mapper.map(69, confidence=0.1))
        stable = mapper.map(69, confidence=0.9)
        low = mapper.map(74, confidence=0.1)
        self.assertEqual(low, stable)

    def test_key_mode_changes_jianpu_only(self):
        self.assertEqual(erhu_jianpu(69, "D"), "5")
        self.assertEqual(erhu_jianpu(69, "G"), "2")

    def test_reset_removes_string_history(self):
        mapper = ErhuMapper()
        mapper.map(67)
        self.assertEqual(mapper.map(69).string_name, "inner")
        mapper.reset()
        self.assertEqual(mapper.map(69).string_name, "outer")


if __name__ == "__main__":
    unittest.main()
