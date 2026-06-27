import ctypes
import platform
import unittest

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
