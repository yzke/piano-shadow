"""Piano Shadow application entry point."""

from __future__ import annotations

import queue
import random
import signal
import sys
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction, QActionGroup, QGuiApplication, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from audio_capture import SystemAudioCapture
from config import (
    AppConfig,
    PIANO_MODEL_PATH,
    PIANO_MODEL_URL,
    ensure_data_layout,
    parse_args,
)
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


def resource_path(relative: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / relative


class TrayController:
    """Persistent Windows notification-area controls."""

    def __init__(self, app: QApplication, window: OverlayWindow) -> None:
        self.app = app
        self.window = window
        icon_path = resource_path("assets/piano-shadow-icon.png")
        self.icon = QIcon(str(icon_path))
        app.setWindowIcon(self.icon)
        window.setWindowIcon(self.icon)
        self.tray = QSystemTrayIcon(self.icon, window)
        self.tray.setToolTip("Piano Shadow")
        self.menu = QMenu()

        self.show_action = QAction("隐藏悬浮窗", self.menu)
        self.show_action.triggered.connect(self._toggle_window)
        self.top_action = QAction("始终置顶", self.menu, checkable=True)
        self.top_action.triggered.connect(window._toggle_topmost)
        self.lock_action = QAction("锁定（同时鼠标穿透）", self.menu, checkable=True)
        self.lock_action.triggered.connect(window._toggle_position_lock)
        self.minimal_action = QAction("纯键盘模式", self.menu, checkable=True)
        self.minimal_action.triggered.connect(window._toggle_keyboard_only)
        self.menu.addAction(self.show_action)
        self.menu.addAction(self.top_action)
        self.menu.addAction(self.lock_action)
        self.menu.addAction(self.minimal_action)
        self.menu.addSeparator()

        model_menu = self.menu.addMenu("识别模型")
        basic = QAction("Basic Pitch · CPU", model_menu, checkable=True)
        gpu = QAction("Piano GPU · 推荐", model_menu, checkable=True)
        group = QActionGroup(model_menu)
        group.setExclusive(True)
        group.addAction(basic)
        group.addAction(gpu)
        basic.triggered.connect(lambda checked: checked and window._select_model("basic-pitch"))
        gpu.triggered.connect(lambda checked: checked and window._select_model("piano-gpu"))
        model_menu.addAction(basic)
        model_menu.addAction(gpu)
        self.model_actions = {"basic-pitch": basic, "piano-gpu": gpu}

        download = QAction("下载 Piano GPU 模型…", self.menu)
        download.triggered.connect(
            lambda: window.model_download_required.emit(
                str(PIANO_MODEL_PATH), PIANO_MODEL_URL
            )
        )
        self.menu.addAction(download)
        self.menu.addSeparator()
        reset_action = QAction("恢复默认设置…", self.menu)
        reset_action.triggered.connect(window.reset_settings)
        self.menu.addAction(reset_action)
        self.menu.addSeparator()
        quit_action = QAction("退出 Piano Shadow", self.menu)
        quit_action.triggered.connect(app.quit)
        self.menu.addAction(quit_action)
        self.menu.aboutToShow.connect(self._sync)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        self.tray.show()
        self._sync()

    def _sync(self) -> None:
        self.show_action.setText("隐藏悬浮窗" if self.window.isVisible() else "显示悬浮窗")
        self.top_action.setChecked(self.window._always_on_top)
        self.lock_action.setChecked(self.window._position_locked)
        self.minimal_action.setChecked(self.window._keyboard_only)
        self.model_actions[self.window.config.model].setChecked(True)

    def _toggle_window(self) -> None:
        self.window.hide() if self.window.isVisible() else self.window.show()
        self._sync()

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._toggle_window()


def run(config: AppConfig) -> int:
    ensure_data_layout()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        QtHighDpiScaleFactorRoundingPolicy
    )
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Piano Shadow")
    app.setWindowIcon(QIcon(str(resource_path("assets/piano-shadow-icon.png"))))
    app.setQuitOnLastWindowClosed(True)
    window = OverlayWindow(config)
    window.show()
    window.restore_settings()
    tray = TrayController(app, window) if QSystemTrayIcon.isSystemTrayAvailable() else None
    if tray:
        app.setQuitOnLastWindowClosed(False)
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
            if model_name == "piano-gpu":
                worker = worker_class(
                    config,
                    audio_queue,
                    window.notes_received.emit,
                    window.status_received.emit,
                    window.model_fallback_received.emit,
                    window.model_download_required.emit,
                )
            else:
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
        window.save_settings()
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
