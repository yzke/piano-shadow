"""Cross-platform system-output capture with graceful backend fallback."""

from __future__ import annotations

import platform
import queue
import subprocess
import threading
import warnings
from collections.abc import Callable

import numpy as np


class AudioCaptureError(RuntimeError):
    pass


def _pulse_default_monitor() -> str | None:
    """Return the default Pulse/PipeWire monitor source when pactl is available."""
    try:
        sink = subprocess.run(
            ["pactl", "get-default-sink"], capture_output=True, text=True, timeout=2, check=True
        ).stdout.strip()
        return f"{sink}.monitor" if sink else None
    except (FileNotFoundError, subprocess.SubprocessError):
        return None


class SystemAudioCapture:
    """Capture fixed-size mono float32 chunks on a background thread."""

    def __init__(
        self,
        sample_rate: int,
        chunk_seconds: float,
        output: queue.Queue[np.ndarray],
        status: Callable[[str, bool], None],
    ) -> None:
        self.sample_rate = sample_rate
        self.frames = round(sample_rate * chunk_seconds)
        self.output = output
        self.status = status
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="audio-capture", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _put_latest(self, audio: np.ndarray) -> None:
        try:
            self.output.put(audio, timeout=0.1)
        except queue.Full:
            try:
                self.output.get_nowait()
            except queue.Empty:
                pass
            self.output.put_nowait(audio)

    def _run(self) -> None:
        try:
            self._capture_soundcard()
        except Exception as exc:
            self.status(
                f"未检测到系统音频输入 · 请检查 loopback 或 monitor source（{exc}）",
                True,
            )

    def _select_microphone(self, sc):
        system = platform.system()
        speaker = sc.default_speaker()
        if system == "Windows" and speaker is not None:
            mic = sc.get_microphone(id=str(speaker.id), include_loopback=True)
            if mic is not None:
                return mic

        monitor = _pulse_default_monitor() if system == "Linux" else None
        microphones = sc.all_microphones(include_loopback=True)
        if monitor:
            for mic in microphones:
                if monitor.lower() in (str(mic.id) + " " + mic.name).lower():
                    return mic
        if speaker is not None:
            needle = speaker.name.lower()
            for mic in microphones:
                haystack = (str(mic.id) + " " + mic.name).lower()
                if needle in haystack and ("monitor" in haystack or "loopback" in haystack):
                    return mic
        for mic in microphones:
            haystack = (str(mic.id) + " " + mic.name).lower()
            if "monitor" in haystack or "loopback" in haystack:
                return mic
        return None

    def _capture_soundcard(self) -> None:
        try:
            import soundcard as sc
        except ImportError as exc:
            raise AudioCaptureError("缺少 soundcard，请安装 requirements.txt") from exc
        mic = self._select_microphone(sc)
        if mic is None:
            raise AudioCaptureError("找不到默认扬声器的 monitor/loopback")
        self.status(f"Listening · {mic.name}", False)
        with warnings.catch_warnings():
            warning_type = getattr(sc, "SoundcardRuntimeWarning", Warning)
            warnings.filterwarnings(
                "ignore",
                message="data discontinuity in recording",
                category=warning_type,
            )
            with mic.recorder(samplerate=self.sample_rate, channels=2, blocksize=2048) as recorder:
                while not self._stop.is_set():
                    data = recorder.record(numframes=self.frames)
                    mono = np.asarray(data, dtype=np.float32)
                    if mono.ndim == 2:
                        mono = mono.mean(axis=1)
                    self._put_latest(np.ascontiguousarray(mono))
