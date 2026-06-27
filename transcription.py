"""Basic Pitch transcription worker."""

from __future__ import annotations

import queue
import threading
import tempfile
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
        # Match the GPU worker's temporal design: infer over a stable rolling
        # context, advance by a smaller hop, and publish only new onsets.
        context_seconds = max(1.5, min(2.5, self.config.chunk_seconds * 4))
        hop_seconds = max(0.25, min(0.75, self.config.chunk_seconds))
        context_frames = round(self.config.sample_rate * context_seconds)
        hop_frames = round(self.config.sample_rate * hop_seconds)
        recent_frames = round(self.config.sample_rate * 0.25)
        rolling = np.empty(0, dtype=np.float32)
        frames_since_inference = 0
        stream_frames = 0
        first_window = True
        last_onsets: dict[int, float] = {}
        while not self._stop.is_set():
            try:
                chunk = self.input.get(timeout=0.25)
            except queue.Empty:
                continue
            chunks = [chunk]
            while True:
                try:
                    chunks.append(self.input.get_nowait())
                except queue.Empty:
                    break
            chunk = np.concatenate(chunks)
            stream_frames += chunk.size
            frames_since_inference += chunk.size
            rolling = np.concatenate((rolling, chunk))[-context_frames:]
            if rolling.size < context_frames or frames_since_inference < hop_frames:
                continue
            advanced_frames = frames_since_inference
            frames_since_inference = 0
            audio = np.ascontiguousarray(rolling)
            rms = float(
                np.sqrt(
                    np.mean(np.square(audio[-recent_frames:]), dtype=np.float64)
                )
            )
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
                            minimum_note_length=90,
                            melodia_trick=False,
                        )
                finally:
                    wav_path.unlink(missing_ok=True)
                advanced_seconds = advanced_frames / self.config.sample_rate
                cutoff = (
                    0.0
                    if first_window
                    else max(0.0, context_seconds - advanced_seconds - 0.12)
                )
                window_start = (
                    stream_frames / self.config.sample_rate - context_seconds
                )
                events: list[NoteEvent] = []
                for start, end, pitch, amplitude, *_ in raw_notes:
                    onset = float(start)
                    if onset < cutoff:
                        continue
                    midi = int(pitch)
                    absolute_onset = window_start + onset
                    # Suppress overlap re-detections without blocking genuine
                    # repeated piano strikes.
                    if absolute_onset - last_onsets.get(midi, -1e9) < 0.14:
                        continue
                    last_onsets[midi] = absolute_onset
                    events.append(
                        NoteEvent(
                            midi=midi,
                            start=max(0.0, onset - cutoff),
                            end=max(0.0, float(end) - cutoff),
                            velocity=max(
                                1, min(127, round(float(amplitude) * 127))
                            ),
                            confidence=float(amplitude),
                        )
                    )
                first_window = False
                stale_before = window_start - 1.0
                last_onsets = {
                    midi: onset
                    for midi, onset in last_onsets.items()
                    if onset >= stale_before
                }
                notes = filter_and_merge(
                    events, self.config.min_confidence, self.config.min_velocity
                )
                notes = suppress_weak_harmonics(notes)
                if notes:
                    self.on_notes(notes)
                    self.on_status("Listening · Piano detected", False)
            except Exception as exc:
                self.on_status(f"转录暂时失败 · 将继续监听（{exc}）", True)

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
