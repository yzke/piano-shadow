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
from performance import INSTRUMENTS
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
                "ear_training",
                "instrument_prev",
                "instrument_label",
                "instrument_next",
                "instrument_reset",
                "soundfont_manage",
            ),
        )
        self.assertGreater(
            window._control_rects()["ear_training"].top(),
            window._control_rects()["performance"].top(),
        )
        self.assertEqual(window._performance.input_mode, "keyboard")
        window._activate_control("performance_help")
        self.assertTrue(window._performance_help)
        window._activate_control("input_mode")
        self.assertEqual(window._performance.input_mode, "midi")
        window._toggle_performance_mode(False)
        window.close()

    def test_instrument_controls_update_compact_source_label(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window._toggle_performance_mode(True)
        self.assertEqual(window._performance.sound_label, "WIN · 大钢琴")
        label = window._control_rects()["instrument_label"]
        self.assertGreater(label.width(), label.height() * 3)
        window._activate_control("instrument_next")
        self.assertEqual(window._performance.sound_label, "WIN · 电钢琴")
        window._activate_control("instrument_prev")
        self.assertEqual(window._performance.sound_label, "WIN · 大钢琴")
        window._activate_control("instrument_next")
        window._activate_control("instrument_reset")
        self.assertEqual(window._performance.sound_label, "WIN · 大钢琴")
        self.assertEqual(window._instrument_index, 0)
        self.assertEqual(window._sound_source, "windows")
        window._toggle_performance_mode(False)
        window.close()

    def test_ear_training_control_cycles_levels(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window._toggle_performance_mode(True)
        for expected in (1, 3, 5, 7, 0):
            window._activate_control("ear_training")
            self.assertEqual(
                window._performance.ear_training.note_count,
                expected,
            )
        window._toggle_performance_mode(False)
        window.close()

    def test_ear_training_feedback_records_correct_and_wrong_notes(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window._toggle_performance_mode(True)
        session = window._performance.ear_training
        session.note_count = 3
        session.target = (60, 64, 67)
        session.accepting = True
        window._handle_ear_answer(61)
        self.assertEqual(window._ear_feedback_target, (60, 64, 67))
        self.assertEqual(window._ear_feedback_error, (0, 60, 61))

        window._clear_ear_feedback()
        session.target = (60,)
        session.note_count = 1
        session.accepting = True
        window._handle_ear_answer(60)
        self.assertEqual(window._ear_feedback_target, (60,))
        self.assertIsNone(window._ear_feedback_error)
        self.assertTrue(window._ear_feedback_correct)
        window._toggle_performance_mode(False)
        window.close()

    def test_ear_training_prompt_sounds_without_revealing_key(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window._toggle_performance_mode(True)
        played = []
        window._performance.synth.note_on = (
            lambda midi, velocity: played.append((midi, velocity))
        )
        generation = window._ear_playback_generation
        window.visual_notes.clear()
        window._play_ear_note(generation, 64)
        self.assertEqual(played, [(64, 92)])
        self.assertEqual(window.visual_notes, [])

        window._performance.press("Q")
        self.app.processEvents()
        self.assertTrue(any(note.midi == 60 for note in window.visual_notes))
        window._toggle_performance_mode(False)
        window.close()

    def test_answer_attempt_cancels_pending_prompt_replay(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window._toggle_performance_mode(True)
        session = window._performance.ear_training
        session.note_count = 1
        session.target = (60,)
        session.accepting = True
        generation = window._ear_playback_generation
        window._handle_ear_answer(61)
        self.assertGreater(window._ear_playback_generation, generation)
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

    def test_erhu_space_vibrato_and_alt_glide_controls(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window._instrument_index = len(INSTRUMENTS) - 1
        window._toggle_performance_mode(True)
        bends = []
        window._performance.synth.pitch_bend = bends.append

        space = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Space,
            Qt.KeyboardModifier.NoModifier,
        )
        window.keyPressEvent(space)
        window._vibrato_tick()
        self.assertTrue(window._vibrato_timer.isActive())
        self.assertNotEqual(bends[-1], 8192)
        window.keyReleaseEvent(
            QKeyEvent(
                QEvent.Type.KeyRelease,
                Qt.Key.Key_Space,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        self.assertFalse(window._vibrato_timer.isActive())
        self.assertEqual(bends[-1], 8192)

        window._performance.press("Q")
        glide = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_W,
            Qt.KeyboardModifier.AltModifier,
            "w",
        )
        window.keyPressEvent(glide)
        self.assertEqual(window._performance.current_midi, 62)
        window._glide_step(
            window._glide_generation, 60, 62, 2, 14, 14
        )
        self.assertEqual(bends[-1], 8192)
        window._toggle_performance_mode(False)
        window.close()

    def test_piano_alt_and_alt_space_control_missing_pedals(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window._toggle_performance_mode(True)
        events = []
        window._performance.synth.control_change = (
            lambda controller, value: events.append((controller, value))
        )
        window.keyPressEvent(
            QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_Alt,
                Qt.KeyboardModifier.AltModifier,
            )
        )
        self.assertIn((67, 127), events)
        window.keyPressEvent(
            QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_Space,
                Qt.KeyboardModifier.AltModifier,
            )
        )
        self.assertIn((66, 127), events)
        window.keyReleaseEvent(
            QKeyEvent(
                QEvent.Type.KeyRelease,
                Qt.Key.Key_Space,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        self.assertIn((66, 0), events)
        window.keyReleaseEvent(
            QKeyEvent(
                QEvent.Type.KeyRelease,
                Qt.Key.Key_Alt,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        self.assertIn((67, 0), events)
        window._toggle_performance_mode(False)
        window.close()

    def test_help_text_tracks_current_instrument_technique(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window._toggle_performance_mode(True)
        self.assertIn(
            "选择性延音",
            window._performance_help_text(window._performance),
        )
        window._performance.instrument_index = next(
            index
            for index, (program, _name) in enumerate(INSTRUMENTS)
            if program == 16
        )
        self.assertIn(
            "Leslie",
            window._performance_help_text(window._performance),
        )
        window._toggle_performance_mode(False)
        window.close()

    def test_extended_performance_keys_use_physical_key_codes(self):
        cases = (
            (Qt.Key.Key_F12, "F12"),
            (Qt.Key.Key_8, "8"),
            (Qt.Key.Key_Equal, "="),
            (Qt.Key.Key_I, "I"),
            (Qt.Key.Key_BracketRight, "]"),
            (Qt.Key.Key_K, "K"),
            (Qt.Key.Key_Apostrophe, "'"),
            (Qt.Key.Key_Comma, ","),
            (Qt.Key.Key_Slash, "/"),
        )
        for qt_key, expected in cases:
            with self.subTest(expected):
                event = QKeyEvent(
                    QEvent.Type.KeyPress,
                    qt_key,
                    Qt.KeyboardModifier.NoModifier,
                )
                self.assertEqual(
                    OverlayWindow._performance_key_token(event),
                    expected,
                )

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
            first._instrument_index = 5
            first._sound_source = "soundfont"
            first.save_settings()
            first.close()

            restored = OverlayWindow(AppConfig(demo_mode=True))
            with patch.object(
                OverlayWindow,
                "_soundfont_is_installed",
                return_value=True,
            ):
                restored.restore_settings()
            self.assertEqual(restored._opacity, 0.20)
            self.assertEqual(restored._active_opacity, 0.70)
            self.assertEqual(restored._scale_percent, 120)
            self.assertFalse(restored._show_status)
            self.assertEqual(restored._instrument_index, 5)
            self.assertEqual(restored._sound_source, "soundfont")
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

    def test_soundfont_download_worker_installs_verified_file(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window.soundfont_download_finished_received.disconnect(
            window._finish_soundfont_download
        )
        results = []
        window.soundfont_download_finished_received.connect(
            lambda success, message: results.append((success, message))
        )
        payload = b"piano-shadow-test-soundfont"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.sf2"
            target = root / "soundfonts" / "target.sf2"
            partial = target.with_suffix(".sf2.part")
            source.write_bytes(payload)
            with (
                patch("ui_overlay.SOUNDFONT_MIN_BYTES", 1),
                patch(
                    "ui_overlay.SOUNDFONT_SHA256",
                    hashlib.sha256(payload).hexdigest(),
                ),
            ):
                window._download_soundfont_worker(
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
