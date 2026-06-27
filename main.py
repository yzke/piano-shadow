"""Piano Shadow application entry point."""

from __future__ import annotations

import queue
import random
import signal
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication

from audio_capture import SystemAudioCapture
from config import AppConfig, parse_args
from note_model import NoteEvent, is_piano_note
from piano_transcription import PianoGpuTranscriptionWorker
from transcription import TranscriptionWorker
from ui_overlay import OverlayWindow


class DemoPlayer:
    PROGRESSIONS = (
        (48, 55, 60, 64), (50, 57, 62, 65), (45, 52, 57, 60),
        (43, 50, 55, 59), (53, 60, 65, 69), (55, 62, 67, 71),
    )

    def __init__(self, window: OverlayWindow, custom: str | None) -> None:
        self.window = window
        self.progressions = self._parse(custom) if custom else list(self.PROGRESSIONS)
        self.timer = QTimer(window)
        self.timer.timeout.connect(self.play)
        self.timer.start(1050)
        QTimer.singleShot(250, self.play)

    @staticmethod
    def _parse(value: str) -> list[tuple[int, ...]]:
        try:
            groups = [
                tuple(int(note.strip()) for note in chord.split(","))
                for chord in value.split(";")
            ]
            valid = [group for group in groups if group and all(is_piano_note(n) for n in group)]
            if not valid:
                raise ValueError
            return valid
        except ValueError as exc:
            raise ValueError("--demo-midi 格式错误，示例：60,64,67;62,65,69") from exc

    def play(self) -> None:
        chord = random.choice(self.progressions)
        events = [
            NoteEvent(note, 0, 0.8, random.randint(72, 112), 0.9) for note in chord
        ]
        self.window.add_notes(events)


def run(config: AppConfig) -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        QtHighDpiScaleFactorRoundingPolicy
    )
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Piano Shadow")
    app.setQuitOnLastWindowClosed(True)
    window = OverlayWindow(config)
    window.show()
    workers: list[object] = []

    if config.demo_mode:
        window.set_status("Piano Shadow · Demo")
        try:
            workers.append(DemoPlayer(window, config.demo_midi))
        except ValueError as exc:
            window.set_status(str(exc), True)
    else:
        # Capture at 100 ms granularity. Each backend decides how much context
        # it needs: Basic Pitch batches to config.chunk_seconds, while the
        # piano GPU backend updates a rolling context.
        audio_queue: queue.Queue = queue.Queue(maxsize=40)
        capture = SystemAudioCapture(
            config.sample_rate, 0.1, audio_queue, window.status_received.emit
        )
        current_transcriber: dict[str, object | None] = {"worker": None}

        def start_transcriber(model_name: str) -> None:
            window.set_status(
                "Switching · Piano GPU"
                if model_name == "piano-gpu"
                else "Switching · Basic Pitch",
                False,
            )
            old = current_transcriber["worker"]
            if old is not None:
                old.stop()
            while True:
                try:
                    audio_queue.get_nowait()
                except queue.Empty:
                    break
            config.model = model_name
            worker_class = (
                PianoGpuTranscriptionWorker
                if model_name == "piano-gpu"
                else TranscriptionWorker
            )
            worker = worker_class(
                config,
                audio_queue,
                window.notes_received.emit,
                window.status_received.emit,
            )
            current_transcriber["worker"] = worker
            worker.start()

        window.model_selected.connect(start_transcriber)
        workers.append(capture)
        start_transcriber(config.model)
        capture.start()

    def shutdown() -> None:
        for worker in workers:
            stop = getattr(worker, "stop", None)
            if stop:
                stop()
        if not config.demo_mode:
            transcriber = current_transcriber.get("worker")
            if transcriber is not None:
                transcriber.stop()

    app.aboutToQuit.connect(shutdown)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: None)
    heartbeat.start(500)
    return app.exec()


# Kept as a constant to avoid version-specific Qt enum imports at module import.
from PyQt6.QtCore import Qt
QtHighDpiScaleFactorRoundingPolicy = Qt.HighDpiScaleFactorRoundingPolicy.PassThrough


if __name__ == "__main__":
    try:
        raise SystemExit(run(parse_args()))
    except KeyboardInterrupt:
        raise SystemExit(0)
