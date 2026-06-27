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


if __name__ == "__main__":
    unittest.main()
