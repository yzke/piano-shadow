import ctypes
import hashlib
import platform
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QEvent, QSettings, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

from config import AppConfig
from ui_overlay import OverlayWindow


@unittest.skipUnless(platform.system() == "Windows", "Windows-only native window test")
class WindowsOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_native_topmost_toggle_preserves_position(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window.move(180, 140)
        window.show()
        self.app.processEvents()
        position = window.pos()
        hwnd = int(window.winId())
        get_style = ctypes.windll.user32.GetWindowLongPtrW
        ws_ex_topmost = 0x00000008
        window._toggle_topmost(False)
        self.app.processEvents()
        self.assertFalse(get_style(hwnd, -20) & ws_ex_topmost)
        self.assertEqual(window.pos(), position)

        window._toggle_topmost(True)
        self.app.processEvents()
        self.assertTrue(get_style(hwnd, -20) & ws_ex_topmost)
        self.assertEqual(window.pos(), position)
        window.close()

    def test_lock_controls_mouse_passthrough(self) -> None:
        window = OverlayWindow(AppConfig(demo_mode=True))
        window.show()
        self.app.processEvents()
        get_style = ctypes.windll.user32.GetWindowLongPtrW
        get_style.argtypes = (ctypes.c_void_p, ctypes.c_int)
        get_style.restype = ctypes.c_ssize_t
        ws_ex_transparent = 0x00000020
        window._toggle_position_lock(True)
        self.assertTrue(window._position_locked)
        self.assertTrue(window._click_through)
        self.assertFalse(get_style(int(window.winId()), -20) & ws_ex_transparent)
        lock_center = window._control_rects()["lock"].center().toPoint()
        self.assertTrue(window._locked_hit_is_interactive(lock_center))
        self.assertFalse(window._locked_hit_is_interactive(window.rect().center()))
        window._toggle_position_lock(False)
        self.assertFalse(window._position_locked)
        self.assertFalse(window._click_through)
        window.close()

    def test_model_chip_switches_backend_selection(self):
        config = AppConfig(demo_mode=True, model="basic-pitch")
        window = OverlayWindow(config)
        window._gpu_requirements_confirmed = True
        selected = []
        window.model_selected.connect(selected.append)
        self.assertIn("model", window._control_rects())

        window._activate_control("model")
        self.assertEqual(config.model, "piano-gpu")
        self.assertEqual(selected, ["piano-gpu"])

        window._activate_control("model")
        self.assertEqual(config.model, "basic-pitch")
        self.assertEqual(selected, ["piano-gpu", "basic-pitch"])
        window.close()

    def test_keyboard_and_active_opacity_are_independent(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window._opacity = 1.0
        window._active_opacity = 0.90
        window._activate_control("keyboard_opacity")
        self.assertEqual(window._opacity, 0.0)
        self.assertEqual(window._active_opacity, 0.90)
        window._activate_control("active_opacity")
        self.assertEqual(window._active_key_opacity(), 1.0)
        window._activate_control("active_opacity")
        self.assertEqual(window._active_key_opacity(), 0.30)
        window.close()

    def test_performance_keeps_standard_controls_and_adds_help(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window._toggle_performance_mode(True)
        self.assertEqual(
            tuple(window._control_rects()),
            (
                "performance",
                "minimal",
                "model",
                "lock",
                "top",
                "smaller",
                "larger",
                "keyboard_opacity",
                "active_opacity",
                "input_mode",
                "performance_help",
            ),
        )
        self.assertEqual(window._performance.input_mode, "keyboard")
        window._activate_control("performance_help")
        self.assertTrue(window._performance_help)
        window._activate_control("input_mode")
        self.assertEqual(window._performance.input_mode, "midi")
        window._toggle_performance_mode(False)
        window.close()

    def test_ctrl_performance_key_uses_physical_key_code(self):
        event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Q,
            Qt.KeyboardModifier.ControlModifier,
            "\x11",
        )
        self.assertEqual(OverlayWindow._performance_key_token(event), "Q")

        window = OverlayWindow(AppConfig(demo_mode=True))
        window._toggle_performance_mode(True)
        played = []
        window._performance.synth.note_on = lambda midi, velocity: played.append(midi)
        window.keyPressEvent(event)
        self.assertEqual(played, [59])  # Q is C4; Ctrl lowers it to B3.
        window._toggle_performance_mode(False)
        window.close()

    def test_settings_restore_independent_opacities(self):
        with tempfile.TemporaryDirectory() as directory:
            QSettings.setDefaultFormat(QSettings.Format.IniFormat)
            QSettings.setPath(
                QSettings.Format.IniFormat,
                QSettings.Scope.UserScope,
                directory,
            )
            QSettings("Piano Shadow", "Piano Shadow").clear()
            first = OverlayWindow(AppConfig(demo_mode=True))
            first._opacity = 0.20
            first._active_opacity = 0.70
            first._scale_percent = 120
            first._show_status = False
            first.save_settings()
            first.close()

            restored = OverlayWindow(AppConfig(demo_mode=True))
            restored.restore_settings()
            self.assertEqual(restored._opacity, 0.20)
            self.assertEqual(restored._active_opacity, 0.70)
            self.assertEqual(restored._scale_percent, 120)
            self.assertFalse(restored._show_status)
            restored.close()

    def test_model_download_worker_installs_verified_file(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window.model_download_finished_received.disconnect(
            window._finish_model_download
        )
        results = []
        window.model_download_finished_received.connect(
            lambda success, message: results.append((success, message))
        )
        payload = b"piano-shadow-test-model"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pth"
            target = root / "models" / "target.pth"
            partial = target.with_suffix(".pth.part")
            source.write_bytes(payload)
            with (
                patch("config.PIANO_MODEL_MIN_BYTES", 1),
                patch(
                    "config.PIANO_MODEL_SHA256",
                    hashlib.sha256(payload).hexdigest(),
                ),
            ):
                window._download_model_worker(
                    target, partial, (source.as_uri(),)
                )
            self.app.processEvents()
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(results, [(True, str(target))])
        window.close()

    def test_gpu_fallback_updates_ui_selection(self):
        config = AppConfig(demo_mode=True, model="piano-gpu")
        window = OverlayWindow(config)
        selected = []
        window.model_selected.connect(selected.append)
        window.model_fallback_received.emit("basic-pitch")
        self.app.processEvents()
        self.assertEqual(config.model, "basic-pitch")
        self.assertEqual(selected, ["basic-pitch"])
        window.close()


if __name__ == "__main__":
    unittest.main()
