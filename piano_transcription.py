"""GPU piano-specialist transcription worker."""

from __future__ import annotations

import logging
import contextlib
import io
import queue
import threading
from collections.abc import Callable

import numpy as np

from config import (
    AppConfig,
    PIANO_MODEL_MIN_BYTES,
    PIANO_MODEL_PATH,
    PIANO_MODEL_URL,
)
from note_model import NoteEvent, filter_and_merge


class PianoGpuTranscriptionWorker:
    """Run the high-resolution piano model on a rolling audio context."""

    def __init__(
        self,
        config: AppConfig,
        input_queue: queue.Queue[np.ndarray],
        on_notes: Callable[[list[NoteEvent]], None],
        on_status: Callable[[str, bool], None],
        on_fallback: Callable[[str], None],
        on_download_required: Callable[[str, str], None],
    ) -> None:
        self.config = config
        self.input = input_queue
        self.on_notes = on_notes
        self.on_status = on_status
        self.on_fallback = on_fallback
        self.on_download_required = on_download_required
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="piano-gpu", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        if (
            not PIANO_MODEL_PATH.exists()
            or PIANO_MODEL_PATH.stat().st_size < PIANO_MODEL_MIN_BYTES
        ):
            self.on_status("Piano GPU 模型未安装 · 自动回退 Basic Pitch", True)
            self.on_download_required(str(PIANO_MODEL_PATH), PIANO_MODEL_URL)
            self.on_fallback("basic-pitch")
            return
        previous_logging_level = logging.root.manager.disable
        logging.disable(logging.WARNING)
        try:
            import torch
            from piano_transcription_inference import PianoTranscription, sample_rate
        except Exception as exc:
            self.on_status(f"Piano GPU 不可用 · 请安装 GPU 模型依赖（{exc}）", True)
            logging.disable(previous_logging_level)
            self.on_fallback("basic-pitch")
            return
        finally:
            logging.disable(previous_logging_level)

        if not torch.cuda.is_available():
            self.on_status("Piano GPU 不可用 · 自动回退 Basic Pitch", True)
            self.on_fallback("basic-pitch")
            return
        try:
            gpu_name = torch.cuda.get_device_name(0)
            self.on_status("Loading · Piano GPU", False)
            # The package defaults to 10-second segments and pads shorter
            # inputs with silence. Two seconds is the measured accuracy/latency
            # balance for this desktop association aid.
            with contextlib.redirect_stdout(io.StringIO()):
                transcriptor = PianoTranscription(
                    device="cuda",
                    segment_samples=sample_rate * 2,
                    checkpoint_path=str(PIANO_MODEL_PATH),
                )
            if hasattr(transcriptor.model, "module") and torch.cuda.device_count() == 1:
                transcriptor.model = transcriptor.model.module
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
        except Exception as exc:
            self.on_status(f"Piano GPU 模型加载失败（{exc}）", True)
            self.on_fallback("basic-pitch")
            return

        context_seconds = 2.0
        hop_seconds = 0.1
        context_frames = round(self.config.sample_rate * context_seconds)
        hop_frames = round(self.config.sample_rate * hop_seconds)
        rolling = np.empty(0, dtype=np.float32)
        first_window = True
        stream_frames = 0
        last_onsets: dict[int, float] = {}
        self.on_status("Listening · Piano GPU", False)

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
            new_audio_seconds = chunk.size / self.config.sample_rate
            stream_frames += chunk.size
            rolling = np.concatenate((rolling, chunk))[-context_frames:]
            if rolling.size < context_frames:
                continue
            rms = float(np.sqrt(np.mean(np.square(rolling[-hop_frames:]), dtype=np.float64)))
            if rms < self.config.min_amp:
                continue
            try:
                audio = self._resample(rolling, self.config.sample_rate, sample_rate)
                with contextlib.redirect_stdout(io.StringIO()):
                    result = transcriptor.transcribe(audio, None)
                raw_events = result.get("est_note_events", [])
                cutoff = (
                    0.0
                    if first_window
                    else context_seconds - new_audio_seconds - 0.10
                )
                window_start = stream_frames / self.config.sample_rate - context_seconds
                events: list[NoteEvent] = []
                for event in raw_events:
                    onset = float(event["onset_time"])
                    if onset < cutoff:
                        continue
                    midi = int(event["midi_note"])
                    absolute_onset = window_start + onset
                    if absolute_onset - last_onsets.get(midi, -1e9) < 0.14:
                        continue
                    last_onsets[midi] = absolute_onset
                    events.append(NoteEvent(
                        midi=int(event["midi_note"]),
                        start=max(0.0, onset - cutoff),
                        end=max(0.0, float(event["offset_time"]) - cutoff),
                        velocity=int(event.get("velocity", 90)),
                        confidence=1.0,
                    ))
                first_window = False
                notes = filter_and_merge(
                    events,
                    min_confidence=0.0,
                    min_velocity=self.config.min_velocity,
                )
                if notes:
                    self.on_notes(notes)
            except Exception as exc:
                self.on_status(f"Piano GPU 转录失败 · 将继续监听（{exc}）", True)

    @staticmethod
    def _resample(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
        if source_rate == target_rate:
            return np.ascontiguousarray(audio, dtype=np.float32)
        from scipy.signal import resample_poly

        divisor = np.gcd(source_rate, target_rate)
        output = resample_poly(audio, target_rate // divisor, source_rate // divisor)
        return np.ascontiguousarray(output, dtype=np.float32)
