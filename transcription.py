"""Basic Pitch transcription worker."""

from __future__ import annotations

import queue
import threading
import tempfile
import time
import wave
import contextlib
import io
import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np

from config import AppConfig
from note_model import NoteEvent, filter_and_merge, suppress_weak_harmonics


class TranscriptionWorker:
    def __init__(
        self,
        config: AppConfig,
        input_queue: queue.Queue[np.ndarray],
        on_notes: Callable[[list[NoteEvent]], None],
        on_status: Callable[[str, bool], None],
    ) -> None:
        self.config = config
        self.input = input_queue
        self.on_notes = on_notes
        self.on_status = on_status
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_emitted: dict[int, float] = {}

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="basic-pitch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        previous_logging_level = logging.root.manager.disable
        logging.disable(logging.WARNING)
        try:
            from basic_pitch import ICASSP_2022_MODEL_PATH
            from basic_pitch.inference import Model, predict
        except Exception as exc:
            self.on_status(f"Basic Pitch 不可用 · 可使用 --demo-mode（{exc}）", True)
            logging.disable(previous_logging_level)
            return
        finally:
            logging.disable(previous_logging_level)
        try:
            self.on_status("Loading · Basic Pitch ONNX model…", False)
            model = Model(ICASSP_2022_MODEL_PATH)
        except Exception as exc:
            self.on_status(f"Basic Pitch 模型加载失败（{exc}）", True)
            return
        self.on_status("Listening · Basic Pitch ready", False)
        pending = np.empty(0, dtype=np.float32)
        target_frames = round(self.config.sample_rate * self.config.chunk_seconds)
        while not self._stop.is_set():
            try:
                chunk = self.input.get(timeout=0.25)
            except queue.Empty:
                continue
            pending = np.concatenate((pending, chunk))
            if pending.size < target_frames:
                continue
            audio = np.ascontiguousarray(pending[-target_frames:])
            pending = np.empty(0, dtype=np.float32)
            rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))
            if rms < self.config.min_amp:
                self.on_status("Listening · 等待清晰的钢琴声…", False)
                continue
            try:
                # The public Basic Pitch API consistently accepts file paths across
                # releases; its ndarray API has changed. A short-lived PCM WAV keeps
                # this worker compatible without adding scipy/soundfile.
                wav_path = self._write_wav(audio)
                try:
                    # Reuse the loaded ONNX session. Passing only the path here
                    # would reconstruct the model for every audio chunk.
                    with contextlib.redirect_stdout(io.StringIO()):
                        _, _, raw_notes = predict(
                            str(wav_path),
                            model,
                            onset_threshold=max(0.58, self.config.min_confidence),
                            frame_threshold=max(0.38, self.config.min_confidence * 0.78),
                            minimum_note_length=110,
                            melodia_trick=False,
                        )
                finally:
                    wav_path.unlink(missing_ok=True)
                events = [
                    NoteEvent(
                        midi=int(pitch),
                        start=float(start),
                        end=float(end),
                        velocity=max(1, min(127, round(float(amplitude) * 127))),
                        confidence=float(amplitude),
                    )
                    for start, end, pitch, amplitude, *_ in raw_notes
                ]
                notes = filter_and_merge(
                    events, self.config.min_confidence, self.config.min_velocity
                )
                notes = suppress_weak_harmonics(notes)
                notes = self._limit_repeated_attacks(notes)
                if notes:
                    self.on_notes(notes)
                    self.on_status("Listening · Piano detected", False)
            except Exception as exc:
                self.on_status(f"转录暂时失败 · 将继续监听（{exc}）", True)

    def _limit_repeated_attacks(self, notes: list[NoteEvent]) -> list[NoteEvent]:
        """Avoid resetting a key's fade for every adjacent analysis block."""
        now = time.monotonic()
        cooldown = max(0.75, self.config.chunk_seconds * 1.8)
        emitted: list[NoteEvent] = []
        for note in notes:
            if now - self._last_emitted.get(note.midi, -1e9) >= cooldown:
                emitted.append(note)
                self._last_emitted[note.midi] = now
        stale_before = now - max(4.0, self.config.decay_seconds * 2)
        self._last_emitted = {
            midi: timestamp
            for midi, timestamp in self._last_emitted.items()
            if timestamp >= stale_before
        }
        return emitted

    def _write_wav(self, audio: np.ndarray) -> Path:
        pcm = np.clip(audio, -1.0, 1.0)
        pcm = (pcm * 32767).astype("<i2", copy=False)
        handle = tempfile.NamedTemporaryFile(prefix="piano-shadow-", suffix=".wav", delete=False)
        path = Path(handle.name)
        handle.close()
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.config.sample_rate)
            wav.writeframes(pcm.tobytes())
        return path
