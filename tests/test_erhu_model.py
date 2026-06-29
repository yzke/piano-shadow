import unittest

from erhu_model import ErhuMapper


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
        self.assertEqual((second.position, third.position), (7, 9))

    def test_state_switches_when_other_string_is_materially_closer(self):
        mapper = ErhuMapper()
        mapper.map(62)
        state = mapper.map(74)
        self.assertEqual((state.string_name, state.position), ("outer", 5))

    def test_reset_removes_string_history(self):
        mapper = ErhuMapper()
        mapper.map(67)
        self.assertEqual(mapper.map(69).string_name, "inner")
        mapper.reset()
        self.assertEqual(mapper.map(69).string_name, "outer")


if __name__ == "__main__":
    unittest.main()
