"""Launch a standalone Erhu Shadow UI demo without capture or system tray."""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from config import AppConfig
from main import DemoPlayer
from ui_overlay import OverlayWindow


def main() -> int:
    app = QApplication(sys.argv[:1])
    window = OverlayWindow(AppConfig(demo_mode=True))
    window._set_visual_mode("erhu")
    window.set_status("Erhu Shadow · v0.6.0 Demo")
    window.show()
    demo = DemoPlayer(window, "62;64;66;67;69;71;72;74")
    # Keep Python references alive for the full Qt event loop.
    window._demo_player = demo
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
