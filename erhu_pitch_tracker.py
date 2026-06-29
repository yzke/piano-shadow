"""Realtime monophonic pitch tracker for continuous-pitch instruments."""

from __future__ import annotations

import math
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from config import AppConfig


@dataclass(frozen=True, slots=True)
class PitchEvent:
    frequency: float
    midi_float: float
    confidence: float
    timestamp: float


class ErhuPitchTracker:
    """Track one dominant F0 with low latency; intended for Erhu Shadow."""

    def __init__(
        self,
        config: AppConfig,
        input_queue: queue.Queue[np.ndarray],
        on_pitch: Callable[[PitchEvent], None],
        on_status: Callable[[str, bool], None],
    ) -> None:
        self.config = config
        self.input = input_queue
        self.on_pitch = on_pitch
        self.on_status = on_status
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._smoothed_midi: float | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name="pitch-tracker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.5)

    def _run(self) -> None:
        self.on_status("Listening · Pitch Tracker", False)
        window_frames = max(1024, round(self.config.sample_rate * 0.075))
        recent_frames = round(self.config.sample_rate * 0.035)
        rolling = np.empty(0, dtype=np.float32)
        while not self._stop.is_set():
            try:
                chunk = self.input.get(timeout=0.2)
            except queue.Empty:
                continue
            chunks = [chunk]
            while True:
                try:
                    chunks.append(self.input.get_nowait())
                except queue.Empty:
                    break
            chunk = np.concatenate(chunks).astype(np.float32, copy=False)
            rolling = np.concatenate((rolling, chunk))[-window_frames:]
            if rolling.size < window_frames:
                continue
            recent = rolling[-recent_frames:]
            rms = float(np.sqrt(np.mean(np.square(recent), dtype=np.float64)))
            if rms < self.config.min_amp:
                continue
            estimate = self._estimate_pitch(rolling, self.config.sample_rate)
            if estimate is None:
                continue
            frequency, clarity = estimate
            if clarity < 0.32:
                continue
            midi = 69.0 + 12.0 * math.log2(frequency / 440.0)
            if self._smoothed_midi is None:
                self._smoothed_midi = midi
            else:
                # Enough smoothing to tame bow noise/vibrato jitter while
                # preserving slides as visible continuous motion.
                self._smoothed_midi = self._smoothed_midi * 0.70 + midi * 0.30
            self.on_pitch(
                PitchEvent(
                    frequency=frequency,
                    midi_float=self._smoothed_midi,
                    confidence=max(0.0, min(1.0, clarity)),
                    timestamp=time.monotonic(),
                )
            )

    @staticmethod
    def _estimate_pitch(
        audio: np.ndarray,
        sample_rate: int,
        min_frequency: float = 180.0,
        max_frequency: float = 1600.0,
    ) -> tuple[float, float] | None:
        frame = np.asarray(audio, dtype=np.float32)
        if frame.size < 3:
            return None
        frame = frame - float(np.mean(frame))
        energy = float(np.dot(frame, frame))
        if energy <= 1e-9:
            return None
        window = np.hanning(frame.size).astype(np.float32)
        frame = frame * window
        correlation = np.correlate(frame, frame, mode="full")[frame.size - 1 :]
        if correlation.size < 3 or correlation[0] <= 1e-9:
            return None
        min_lag = max(1, int(sample_rate / max_frequency))
        max_lag = min(correlation.size - 2, int(sample_rate / min_frequency))
        if min_lag >= max_lag:
            return None
        search = correlation[min_lag : max_lag + 1]
        lag = int(np.argmax(search) + min_lag)
        clarity = float(correlation[lag] / correlation[0])
        # Parabolic interpolation around the peak reduces stair-stepping.
        left = float(correlation[lag - 1])
        center = float(correlation[lag])
        right = float(correlation[lag + 1])
        denominator = left - 2.0 * center + right
        if abs(denominator) > 1e-9:
            lag += int(0)
            offset = 0.5 * (left - right) / denominator
        else:
            offset = 0.0
        refined_lag = max(1e-6, lag + max(-0.5, min(0.5, offset)))
        return sample_rate / refined_lag, clarity


PitchTrackerWorker = ErhuPitchTracker
