"""Piano Shadow application entry point."""

from __future__ import annotations

import queue
import random
import signal
import sys
import gc
import threading
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
from erhu_model import ErhuKeyMode
from note_model import NoteEvent, is_piano_note
from piano_transcription import PianoGpuTranscriptionWorker
from erhu_pitch_tracker import ErhuPitchTracker
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

    def set_paused(self, paused: bool) -> None:
        if paused:
            self.timer.stop()
        else:
            self.timer.start(1050)


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
        mode_menu = self.menu.addMenu("可视化模式")
        mode_group = QActionGroup(mode_menu)
        mode_group.setExclusive(True)
        self.piano_mode_action = QAction("钢琴模式", mode_menu, checkable=True)
        self.erhu_mode_action = QAction(
            "二胡模式 · Erhu Shadow", mode_menu, checkable=True
        )
        mode_group.addAction(self.piano_mode_action)
        mode_group.addAction(self.erhu_mode_action)
        mode_menu.addAction(self.piano_mode_action)
        mode_menu.addAction(self.erhu_mode_action)
        self.piano_mode_action.triggered.connect(
            lambda checked: checked and window._set_visual_mode("piano")
        )
        self.erhu_mode_action.triggered.connect(
            lambda checked: checked and window._set_visual_mode("erhu")
        )
        self.menu.addAction(self.top_action)
        self.menu.addAction(self.lock_action)
        self.menu.addAction(self.minimal_action)
        self.menu.addSeparator()

        self.piano_menu = self.menu.addMenu("钢琴功能")
        self.performance_action = QAction(
            "演奏模式", self.piano_menu, checkable=True
        )
        self.performance_action.triggered.connect(window._toggle_performance_mode)
        self.piano_menu.addAction(self.performance_action)
        model_menu = self.piano_menu.addMenu("识别模型 · CPU / GPU")
        basic = QAction("Basic Pitch · CPU", model_menu, checkable=True)
        gpu = QAction("Piano GPU · GPU · 推荐", model_menu, checkable=True)
        group = QActionGroup(model_menu)
        group.setExclusive(True)
        group.addAction(basic)
        group.addAction(gpu)
        basic.triggered.connect(lambda checked: checked and window._select_model("basic-pitch"))
        gpu.triggered.connect(lambda checked: checked and window._select_model("piano-gpu"))
        model_menu.addAction(basic)
        model_menu.addAction(gpu)
        self.model_actions = {"basic-pitch": basic, "piano-gpu": gpu}

        download = QAction("下载 Piano GPU 模型…", self.piano_menu)
        download.triggered.connect(
            lambda: window.model_download_required.emit(
                str(PIANO_MODEL_PATH), PIANO_MODEL_URL
            )
        )
        self.piano_menu.addAction(download)
        self.erhu_menu = self.menu.addMenu("二胡功能")
        self.erhu_vertical_action = QAction(
            "竖向琴弦", self.erhu_menu, checkable=True
        )
        self.erhu_history_action = QAction(
            "显示历史轨迹", self.erhu_menu, checkable=True
        )
        self.erhu_body_action = QAction(
            "显示二胡结构件", self.erhu_menu, checkable=True
        )
        self.erhu_mirror_action = QAction(
            "镜像二胡视角", self.erhu_menu, checkable=True
        )
        self.erhu_vertical_action.triggered.connect(
            lambda checked: window._set_erhu_orientation(checked)
        )
        self.erhu_history_action.triggered.connect(
            lambda checked: window._activate_control("erhu_history")
            if checked != window._erhu_history
            else None
        )
        self.erhu_body_action.triggered.connect(
            lambda checked: window._activate_control("erhu_body")
            if checked != window._erhu_body
            else None
        )
        self.erhu_mirror_action.triggered.connect(
            lambda checked: window._activate_control("erhu_mirror")
            if checked != window._erhu_mirrored
            else None
        )
        self.erhu_key_menu = self.erhu_menu.addMenu("调式显示")
        self.erhu_key_actions: dict[ErhuKeyMode, QAction] = {}
        erhu_key_group = QActionGroup(self.erhu_key_menu)
        erhu_key_group.setExclusive(True)
        for title, mode in (
            ("自动", ErhuKeyMode.AUTO),
            ("D调", ErhuKeyMode.D),
            ("G调", ErhuKeyMode.G),
            ("F调", ErhuKeyMode.F),
            ("Bb调", ErhuKeyMode.BB),
            ("C调", ErhuKeyMode.C),
            ("A调", ErhuKeyMode.A),
        ):
            action = QAction(title, self.erhu_key_menu, checkable=True)
            action.triggered.connect(
                lambda checked, selected=mode: checked
                and window._set_erhu_key_mode(selected)
            )
            erhu_key_group.addAction(action)
            self.erhu_key_menu.addAction(action)
            self.erhu_key_actions[mode] = action
        self.erhu_menu.addAction(self.erhu_vertical_action)
        self.erhu_menu.addAction(self.erhu_history_action)
        self.erhu_menu.addAction(self.erhu_body_action)
        self.erhu_menu.addAction(self.erhu_mirror_action)
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
        self.minimal_action.setText(
            "纯键盘模式" if self.window._visual_mode == "piano" else "纯二胡可视化"
        )
        self.performance_action.setChecked(self.window._performance_mode)
        is_piano = self.window._visual_mode == "piano"
        self.piano_mode_action.setChecked(is_piano)
        self.erhu_mode_action.setChecked(not is_piano)
        self.piano_menu.setEnabled(is_piano)
        self.erhu_menu.setEnabled(not is_piano)
        self.erhu_vertical_action.setChecked(self.window._erhu_vertical)
        self.erhu_history_action.setChecked(self.window._erhu_history)
        self.erhu_body_action.setEnabled(
            (not is_piano) and self.window._erhu_vertical
        )
        self.erhu_body_action.setChecked(
            self.window._erhu_vertical and self.window._erhu_body
        )
        self.erhu_mirror_action.setEnabled(
            not is_piano
        )
        self.erhu_mirror_action.setChecked(
            (not is_piano) and self.window._erhu_mirrored
        )
        for mode, action in self.erhu_key_actions.items():
            action.setChecked(self.window._erhu_key_mode == mode)
        model_action = self.model_actions.get(self.window.config.model)
        if model_action is not None:
            model_action.setChecked(True)

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
            demo = DemoPlayer(window, config.demo_midi)
            workers.append(demo)
            window.performance_mode_changed.connect(demo.set_paused)
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
        current_transcriber: dict[str, object | int | None] = {
            "worker": None,
            "generation": 0,
        }
        switch_lock = threading.Lock()
        switch_serial_lock = threading.Lock()
        recognition_paused = threading.Event()

        def start_transcriber(model_name: str) -> None:
            with switch_lock:
                current_transcriber["generation"] += 1
                generation = int(current_transcriber["generation"])
            window.set_status(
                "Switching · Piano GPU"
                if model_name == "piano-gpu"
                else (
                    "Switching · Pitch Tracker"
                    if model_name == "pitch-tracker"
                    else "Switching · Basic Pitch 主旋律"
                ),
                False,
            )
            config.model = model_name

            def is_current() -> bool:
                with switch_lock:
                    return (
                        generation == current_transcriber["generation"]
                        and not recognition_paused.is_set()
                    )

            def perform_switch() -> None:
                with switch_lock:
                    old = current_transcriber["worker"]
                    current_transcriber["worker"] = None
                if old is not None:
                    old.stop()
                gc.collect()
                torch_module = sys.modules.get("torch")
                if (
                    torch_module is not None
                    and getattr(torch_module, "cuda", None) is not None
                    and torch_module.cuda.is_available()
                ):
                    torch_module.cuda.empty_cache()
                if not is_current():
                    return
                while True:
                    try:
                        audio_queue.get_nowait()
                    except queue.Empty:
                        break
                worker_class = (
                    PianoGpuTranscriptionWorker
                    if model_name == "piano-gpu"
                    else (
                        ErhuPitchTracker
                        if model_name == "pitch-tracker"
                        else TranscriptionWorker
                    )
                )
                on_notes = (
                    lambda notes: is_current()
                    and window.notes_received.emit(notes)
                )
                on_status = (
                    lambda text, error=False: is_current()
                    and window.status_received.emit(text, error)
                )
                if model_name == "piano-gpu":
                    worker = worker_class(
                        config,
                        audio_queue,
                        on_notes,
                        on_status,
                        lambda fallback: is_current()
                        and window.model_fallback_received.emit(fallback),
                        lambda path, url: is_current()
                        and window.model_download_required.emit(path, url),
                    )
                elif model_name == "pitch-tracker":
                    worker = worker_class(
                        config,
                        audio_queue,
                        lambda pitch: is_current()
                        and window.pitch_received.emit(pitch),
                        on_status,
                    )
                else:
                    worker = worker_class(
                        config, audio_queue, on_notes, on_status
                    )
                with switch_lock:
                    if (
                        generation != current_transcriber["generation"]
                        or recognition_paused.is_set()
                    ):
                        return
                    current_transcriber["worker"] = worker
                worker.start()

            def switch_worker() -> None:
                # Only one generation may stop/start workers at a time. Newer
                # generations wait, then discard superseded work via is_current.
                with switch_serial_lock:
                    perform_switch()

            threading.Thread(
                target=switch_worker,
                name=f"switch-{model_name}-{generation}",
                daemon=True,
            ).start()

        window.model_selected.connect(start_transcriber)

        def set_performance_mode(enabled: bool) -> None:
            if enabled:
                recognition_paused.set()
                with switch_lock:
                    current_transcriber["generation"] += 1
                    old = current_transcriber["worker"]
                    current_transcriber["worker"] = None
                if old is not None:
                    old.stop()
                while True:
                    try:
                        audio_queue.get_nowait()
                    except queue.Empty:
                        break
                window.set_status("演奏模式 · 音频识别已暂停", False)
            else:
                recognition_paused.clear()
                with switch_lock:
                    worker_missing = current_transcriber["worker"] is None
                if worker_missing:
                    start_transcriber(config.model)

        window.performance_mode_changed.connect(set_performance_mode)
        workers.append(capture)
        start_transcriber(config.model)
        capture.start()

    def shutdown() -> None:
        window.save_settings()
        if window._performance is not None:
            window._performance.close()
            window._performance = None
        for worker in workers:
            stop = getattr(worker, "stop", None)
            if stop:
                stop()
        if not config.demo_mode:
            recognition_paused.set()
            with switch_lock:
                current_transcriber["generation"] += 1
                transcriber = current_transcriber.get("worker")
                current_transcriber["worker"] = None
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
