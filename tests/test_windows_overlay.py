import ctypes
import hashlib
import platform
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt
from PyQt6.QtGui import QImage, QKeyEvent, QPainter
from PyQt6.QtWidgets import QApplication

from config import AppConfig
from erhu_model import ErhuKeyMode
from note_model import NoteEvent
from performance import INSTRUMENTS
from erhu_pitch_tracker import PitchEvent
from ui_overlay import ERHU_D_JIANPU, OverlayWindow


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

    def test_basic_pitch_bridge_is_packaged_by_windows_build(self):
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / "basic_pitch_bridge.py").exists())
        self.assertIn(
            "basic_pitch_bridge.py",
            (root / "build-windows.ps1").read_text(encoding="utf-8"),
        )

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
        self.assertTrue(get_style(int(window.winId()), -20) & ws_ex_transparent)
        self.assertIsNotNone(window._unlock_button)
        self.assertTrue(window._unlock_button.isVisible())
        lock_center = window._control_rects()["lock"].center().toPoint()
        self.assertTrue(window._locked_hit_is_interactive(lock_center))
        self.assertFalse(window._locked_hit_is_interactive(window.rect().center()))
        window._toggle_position_lock(False)
        self.assertFalse(window._position_locked)
        self.assertFalse(window._click_through)
        self.assertFalse(get_style(int(window.winId()), -20) & ws_ex_transparent)
        self.assertFalse(window._unlock_button.isVisible())
        window.close()

    def test_model_chip_switches_backend_selection(self):
        config = AppConfig(demo_mode=True, model="basic-pitch")
        window = OverlayWindow(config)
        window._gpu_requirements_confirmed = True
        selected = []
        window.model_selected.connect(selected.append)
        self.assertIn("piano_model", window._control_rects())

        window._activate_control("piano_model")
        self.assertEqual(config.model, "piano-gpu")
        self.assertEqual(selected, ["piano-gpu"])

        window._activate_control("piano_model")
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
                "visual_mode",
                "minimal",
                "lock",
                "top",
                "smaller",
                "larger",
                "keyboard_opacity",
                "active_opacity",
                "performance",
                "staff",
                "piano_model",
                "input_mode",
                "performance_help",
                "ear_training",
                "performance_nav",
                "instrument_prev",
                "instrument_label",
                "instrument_next",
                "instrument_reset",
                "soundfont_manage",
            ),
        )
        self.assertGreater(
            window._control_rects()["ear_training"].top(),
            window._control_rects()["visual_mode"].top(),
        )
        self.assertEqual(window._performance.input_mode, "keyboard")
        window._activate_control("performance_help")
        self.assertTrue(window._performance_help)
        window._activate_control("input_mode")
        self.assertEqual(window._performance.input_mode, "midi")
        window._toggle_performance_mode(False)
        window.close()

    def test_staff_shadow_toggle_extends_window_and_records_notes(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        base_height = window.height()
        self.assertIn("staff", window._control_rects())

        window._activate_control("staff")
        self.assertTrue(window._staff_enabled)
        self.assertGreater(window.height(), base_height)

        window._display_notes([NoteEvent(60, 0.0, 0.45, 96, 0.95)])
        self.assertEqual([note.midi for note in window.staff_notes], [60])

        window._set_visual_mode("erhu")
        self.assertFalse(window._staff_enabled)
        self.assertEqual(window.staff_notes, [])
        self.assertEqual(window.height(), base_height)
        window.close()

    def test_keyboard_only_keeps_staff_when_staff_shadow_is_enabled(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        base_height = window.height()
        window._toggle_staff_shadow(True)
        staff_height = window.height()

        window._toggle_keyboard_only(True)
        self.assertTrue(window._keyboard_only)
        self.assertTrue(window._staff_enabled)
        self.assertGreater(window.height(), base_height)
        self.assertEqual(window.height(), staff_height)

        white, _black = window._keyboard_geometry()
        self.assertIsNotNone(window._staff_rect(white))
        self.assertEqual(tuple(window._control_rects()), ("lock",))
        window._toggle_keyboard_only(False)
        window.close()

    def test_staff_shadow_area_is_mouse_passthrough_when_locked(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window._toggle_staff_shadow(True)
        window._toggle_keyboard_only(True)

        white, _black = window._keyboard_geometry()
        staff_rect = window._staff_rect(white)
        self.assertIsNotNone(staff_rect)
        self.assertFalse(
            window._locked_hit_is_interactive(staff_rect.center().toPoint())
        )
        self.assertTrue(
            window._locked_hit_is_interactive(
                window._control_rects()["lock"].center().toPoint()
            )
        )
        window.close()

    def test_large_locked_overlay_only_keeps_lock_button_interactive(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window.setFixedSize(1280, 720)
        window._toggle_position_lock(True)

        lock_center = window._control_rects()["lock"].center().toPoint()
        self.assertTrue(window._locked_hit_is_interactive(lock_center))
        for point in (
            QPoint(24, 24),
            window.rect().center(),
            QPoint(window.width() - 24, window.height() - 24),
        ):
            self.assertFalse(window._locked_hit_is_interactive(point))
        window.close()

    def test_staff_spelling_uses_sharp_positions(self):
        self.assertEqual(OverlayWindow._staff_spelling(60), ("C", 28, False))
        self.assertEqual(OverlayWindow._staff_spelling(61), ("C", 28, True))

    def test_performance_nav_control_changes_scale_and_octave(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window._toggle_performance_mode(True)
        rect = window._control_rects()["performance_nav"]

        window._activate_performance_nav(rect.center() + QPointF(rect.width() * 0.36, 0))
        self.assertEqual(window._performance.scale_name, "G 大调 / E 小调")

        window._activate_performance_nav(rect.center() - QPointF(rect.width() * 0.36, 0))
        self.assertEqual(window._performance.scale_name, "C 大调 / A 小调")

        window._activate_performance_nav(rect.center() + QPointF(0, rect.height() * 0.36))
        self.assertEqual(window._performance.octave_shift, 1)

        window._activate_performance_nav(rect.center() - QPointF(0, rect.height() * 0.36))
        self.assertEqual(window._performance.octave_shift, 0)
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
            first._instrument_index = 5
            first._sound_source = "soundfont"
            first._visual_mode = "erhu"
            first._erhu_key_mode = ErhuKeyMode.G
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
            self.assertEqual(restored._instrument_index, 5)
            self.assertEqual(restored._sound_source, "soundfont")
            self.assertEqual(restored._visual_mode, "piano")
            self.assertEqual(restored.config.model, "piano-gpu")
            self.assertEqual(restored._erhu_key_mode, ErhuKeyMode.G)
            restored.close()

    def test_erhu_mode_selects_only_strongest_melody_note(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window._set_visual_mode("erhu")
        window._display_notes(
            [
                NoteEvent(62, 0, 0.5, 120, 0.70),
                NoteEvent(69, 0, 0.5, 80, 0.95),
                NoteEvent(74, 0, 0.5, 127, 0.80),
            ]
        )
        self.assertIsNotNone(window._erhu_state)
        self.assertEqual(window._erhu_state.midi, 69)
        self.assertEqual(window._erhu_state.string_name, "outer")
        self.assertEqual(window.visual_notes, [])
        window.close()

    def test_erhu_pitch_event_drives_float_position(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window._set_visual_mode("erhu")
        window.add_pitch(PitchEvent(440.0, 69.5, 0.88, 0.0))
        self.assertIsNotNone(window._erhu_state)
        self.assertEqual(window._erhu_state.string_name, "outer")
        self.assertAlmostEqual(window._erhu_state.position, 0.5)
        self.assertAlmostEqual(window._erhu_target_position, 0.5)
        window.close()

    def test_erhu_loading_ignores_notes_until_pitch_tracker_ready(self):
        window = OverlayWindow(AppConfig())
        window._set_visual_mode("erhu")
        window._display_notes([NoteEvent(69, 0, 0.5, 100, 0.9)])
        window.add_pitch(PitchEvent(440.0, 69.0, 0.9, 0.0))
        self.assertIsNone(window._erhu_state)

        window.set_status("Listening · Pitch Tracker", False)
        window.add_pitch(PitchEvent(440.0, 69.0, 0.9, 0.1))
        self.assertIsNotNone(window._erhu_state)
        self.assertEqual(window._erhu_state.string_name, "outer")
        window.close()

    def test_erhu_string_color_offset_preserves_hue_and_changes_lightness(self):
        inner = OverlayWindow._erhu_note_color(69, "inner")
        outer = OverlayWindow._erhu_note_color(69, "outer")
        inner_hue, _, inner_lightness, _ = inner.getHslF()
        outer_hue, _, outer_lightness, _ = outer.getHslF()
        self.assertAlmostEqual(inner_hue, outer_hue, places=3)
        self.assertGreater(outer_lightness, inner_lightness)
        self.assertGreater(outer_lightness - inner_lightness, 0.10)

    def test_erhu_history_alpha_halves_by_note_order(self):
        self.assertEqual(
            [OverlayWindow._erhu_history_alpha(index) for index in range(5)],
            [128, 64, 32, 16, 8],
        )
        self.assertEqual(OverlayWindow._erhu_history_alpha(-1), 0)
        self.assertEqual(
            [OverlayWindow._erhu_history_diameter(index) for index in range(3)],
            [13.5, 12.75, 12.0],
        )
        self.assertEqual(OverlayWindow._erhu_history_diameter(-1), 0.0)

    def test_erhu_body_geometry_aligns_with_vertical_strings(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window._set_visual_mode("erhu")
        window._activate_control("erhu_rotate")
        axes = {
            "inner": window.width() * 0.36,
            "outer": window.width() * 0.62,
        }
        rect = window._erhu_body_rect(
            vertical=True,
            bottom=window.height() - 17.0,
            string_axis=axes,
        )
        self.assertLess(rect.left(), axes["inner"])
        self.assertGreater(rect.right(), axes["outer"])
        self.assertGreaterEqual(rect.width(), abs(axes["outer"] - axes["inner"]) + 68)
        self.assertGreater(
            axes["inner"] - rect.left(),
            rect.right() - axes["outer"],
        )
        window.close()

    def test_erhu_vertical_string_spacing_follows_structure_visibility_and_mirror(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window._set_visual_mode("erhu")
        window._activate_control("erhu_rotate")
        narrow = window._erhu_vertical_string_axis()
        self.assertLess(narrow["inner"], narrow["outer"])
        self.assertAlmostEqual(narrow["inner"], window.width() * 0.49)
        window._activate_control("erhu_mirror")
        mirrored = window._erhu_vertical_string_axis()
        self.assertGreater(mirrored["inner"], mirrored["outer"])
        rect = window._erhu_body_rect(
            vertical=True,
            bottom=window.height() - 17.0,
            string_axis=narrow,
        )
        body_center = rect.center().x()
        narrow_center = (narrow["inner"] + narrow["outer"]) / 2
        mirrored_center = (mirrored["inner"] + mirrored["outer"]) / 2
        self.assertAlmostEqual(
            narrow_center - body_center,
            body_center - mirrored_center,
            delta=0.1,
        )
        window._activate_control("erhu_body")
        wide = window._erhu_vertical_string_axis()
        self.assertGreater(abs(wide["inner"] - wide["outer"]), abs(narrow["inner"] - narrow["outer"]))
        self.assertAlmostEqual(wide["outer"], window.width() * 0.36)
        window.close()

    def test_erhu_vertical_labels_follow_strings_without_overlap(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window._set_visual_mode("erhu")
        window._activate_control("erhu_rotate")
        axes = window._erhu_vertical_string_axis()
        rects = window._erhu_vertical_label_rects(top=88.0, string_axis=axes)
        note_rect = window._erhu_vertical_note_rect()
        self.assertLess(note_rect.bottom(), rects["inner"].top())
        self.assertLess(note_rect.bottom(), rects["outer"].top())
        self.assertLess(note_rect.top(), 50)
        self.assertFalse(rects["inner"].intersects(rects["outer"]))
        self.assertEqual(rects["inner"].top(), rects["outer"].top())
        window._activate_control("erhu_mirror")
        mirrored = window._erhu_vertical_label_rects(
            top=88.0,
            string_axis=window._erhu_vertical_string_axis(),
        )
        self.assertFalse(mirrored["inner"].intersects(mirrored["outer"]))
        self.assertEqual(mirrored["inner"].top(), mirrored["outer"].top())
        window.close()

    def test_erhu_vertical_position_places_open_string_above_high_position(self):
        top = 88.0
        bottom = 188.0
        self.assertLess(
            OverlayWindow._erhu_vertical_position_y(top, bottom, 0),
            OverlayWindow._erhu_vertical_position_y(top, bottom, 18),
        )

    def test_erhu_top_bars_cover_vertical_strings(self):
        axes = {"inner": 96.0, "outer": 166.0}
        upper, lower = OverlayWindow._erhu_top_bar_rects(top=88.0, string_axis=axes)
        self.assertLess(upper.left(), axes["inner"])
        self.assertGreater(upper.right(), axes["outer"])
        self.assertLess(lower.left(), axes["inner"])
        self.assertGreater(lower.right(), axes["outer"])
        self.assertGreater(upper.width(), lower.width())
        self.assertGreater(
            axes["inner"] - upper.left(),
            upper.right() - axes["outer"],
        )

    def test_erhu_mode_demo_sequence_is_stable_and_tracks_pitch(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window._set_visual_mode("erhu")
        seen = []
        for midi in (62, 64, 66, 67, 69, 71, 72, 74):
            window._display_notes([NoteEvent(midi, 0, 0.5, 90, 0.9)])
            seen.append(window._erhu_state.string_name)
        self.assertEqual(seen, ["inner"] * len(seen))
        self.assertEqual(window._erhu_state.note_name, "D5")
        self.assertEqual(window._erhu_state.position, 12)
        window.close()

    def test_visual_mode_switch_resets_mode_specific_state(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window._set_visual_mode("erhu")
        window._display_notes([NoteEvent(69, 0, 0.5, 90, 0.9)])
        self.assertIsNotNone(window._erhu_state)
        window._set_visual_mode("piano")
        self.assertEqual(window._visual_mode, "piano")
        self.assertIsNone(window._erhu_state)
        self.assertEqual(window._erhu_trails, [])
        window.close()

    def test_top_control_toggles_piano_and_erhu_modes(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        selected_models = []
        selected_modes = []
        window.model_selected.connect(selected_models.append)
        window.visual_mode_changed.connect(selected_modes.append)
        controls = window._control_rects()
        self.assertIn("visual_mode", controls)
        self.assertGreater(
            controls["performance"].top(),
            controls["visual_mode"].top(),
        )
        self.assertEqual(window._visual_mode, "piano")
        window._activate_control("visual_mode")
        self.assertEqual(window._visual_mode, "erhu")
        self.assertEqual(window.config.model, "pitch-tracker")
        self.assertIn("Erhu Shadow", window.status_text)
        window._activate_control("visual_mode")
        self.assertEqual(window._visual_mode, "piano")
        self.assertEqual(window.config.model, "piano-gpu")
        self.assertIn("钢琴模式", window.status_text)
        self.assertEqual(selected_models, ["pitch-tracker", "piano-gpu"])
        self.assertEqual(selected_modes, ["erhu", "piano"])
        window.close()

    def test_erhu_mode_disables_manual_cpu_gpu_model_switch(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        selected = []
        window.model_selected.connect(selected.append)
        window._set_visual_mode("erhu")
        self.assertEqual(window.config.model, "pitch-tracker")
        self.assertNotIn("piano_model", window._control_rects())
        selected.clear()
        window._select_model("piano-gpu")
        self.assertEqual(window.config.model, "pitch-tracker")
        self.assertEqual(selected, [])
        window.close()

    def test_erhu_second_row_rotates_strings_without_hiding_common_controls(self):
        window = OverlayWindow(AppConfig(demo_mode=True))
        window._set_visual_mode("erhu")
        controls = window._control_rects()
        self.assertIn("erhu_rotate", controls)
        self.assertGreater(
            controls["erhu_rotate"].top(),
            controls["visual_mode"].top(),
        )
        for name in (
            "visual_mode",
            "minimal",
            "lock",
            "top",
            "smaller",
            "larger",
            "keyboard_opacity",
            "active_opacity",
        ):
            self.assertIn(name, controls)
        self.assertFalse(window._erhu_vertical)
        self.assertIn("erhu_body", controls)
        self.assertIn("erhu_mirror", controls)
        self.assertFalse(window._control_enabled("erhu_body"))
        self.assertTrue(window._control_enabled("erhu_mirror"))
        normal_horizontal = window._erhu_horizontal_string_axis()
        self.assertLess(normal_horizontal["inner"], normal_horizontal["outer"])
        window._activate_control("erhu_mirror")
        mirrored_horizontal = window._erhu_horizontal_string_axis()
        self.assertGreater(mirrored_horizontal["inner"], mirrored_horizontal["outer"])
        self.assertTrue(window._erhu_mirrored)
        window._activate_control("erhu_mirror")
        self.assertFalse(window._erhu_mirrored)
        horizontal_size = window.size()
        window._activate_control("erhu_rotate")
        self.assertTrue(window._erhu_vertical)
        self.assertTrue(window._erhu_body)
        self.assertTrue(window._control_enabled("erhu_body"))
        self.assertTrue(window._control_enabled("erhu_mirror"))
        self.assertEqual(window.width(), horizontal_size.height())
        self.assertEqual(window.height(), horizontal_size.width())
        self.assertIn("竖向", window.status_text)
        window._display_notes([NoteEvent(69, 0, 0.5, 90, 0.9)])
        image = QImage(
            window.width(),
            window.height(),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        window._draw_erhu(painter, window._erhu_trails[-1].born)
        painter.end()
        self.assertFalse(image.isNull())
        self.assertEqual(ERHU_D_JIANPU[69 % 12], "5")
        self.assertIn("erhu_history", window._control_rects())
        self.assertIn("erhu_body", window._control_rects())
        self.assertIn("erhu_mirror", window._control_rects())
        self.assertTrue(window._erhu_body)
        window._activate_control("erhu_body")
        self.assertFalse(window._erhu_body)
        self.assertIn("二胡结构件", window.status_text)
        window._activate_control("erhu_history")
        self.assertFalse(window._erhu_history)
        self.assertEqual(window._erhu_trails, [])
        window._activate_control("erhu_rotate")
        self.assertFalse(window._erhu_vertical)
        self.assertEqual(window.size(), horizontal_size)
        window.close()

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
