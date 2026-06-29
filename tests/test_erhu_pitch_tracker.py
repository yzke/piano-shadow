import math
import unittest

import numpy as np

from erhu_pitch_tracker import ErhuPitchTracker


class PitchTrackerTests(unittest.TestCase):
    def test_estimates_sine_frequency(self):
        sample_rate = 22050
        frequency = 440.0
        t = np.arange(round(sample_rate * 0.08), dtype=np.float32) / sample_rate
        audio = np.sin(2 * math.pi * frequency * t).astype(np.float32)
        estimate = ErhuPitchTracker._estimate_pitch(audio, sample_rate)
        self.assertIsNotNone(estimate)
        estimated_frequency, clarity = estimate
        self.assertAlmostEqual(estimated_frequency, frequency, delta=3.0)
        self.assertGreater(clarity, 0.4)

    def test_rejects_silence(self):
        audio = np.zeros(2048, dtype=np.float32)
        self.assertIsNone(ErhuPitchTracker._estimate_pitch(audio, 22050))
