"""Configuration and command-line parsing for Piano Shadow."""

from __future__ import annotations

import argparse
import os
import platform
from pathlib import Path

PIANO_MODEL_URLS = (
    "https://github.com/yzke/piano-shadow/releases/download/v0.2.1/"
    "note_F1%3D0.9677_pedal_F1%3D0.9186.pth",
    "https://zenodo.org/records/4034264/files/"
    "CRNN_note_F1%3D0.9677_pedal_F1%3D0.9186.pth?download=1",
)
PIANO_MODEL_URL = PIANO_MODEL_URLS[0]
APP_DATA_DIR = (
    Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    / "PianoShadow"
    if platform.system() == "Windows"
    else Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    / "PianoShadow"
)
MODEL_DIR = APP_DATA_DIR / "models"
LOG_DIR = APP_DATA_DIR / "logs"
PIANO_MODEL_FILENAME = "note_F1=0.9677_pedal_F1=0.9186.pth"
PIANO_MODEL_PATH = MODEL_DIR / PIANO_MODEL_FILENAME
LEGACY_PIANO_MODEL_PATH = (
    Path.home() / "piano_transcription_inference_data" / PIANO_MODEL_FILENAME
)
PIANO_MODEL_MIN_BYTES = 160_000_000
PIANO_MODEL_SHA256 = "c3fa9730725bf4a762f1c14bc80cd5986eacda01b026f5a4a2525cd607876141"


def ensure_data_layout() -> None:
    """Create writable per-user directories and preserve an existing model."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not PIANO_MODEL_PATH.exists() and LEGACY_PIANO_MODEL_PATH.exists():
        os.replace(LEGACY_PIANO_MODEL_PATH, PIANO_MODEL_PATH)
from dataclasses import dataclass


@dataclass(slots=True)
class AppConfig:
    chunk_seconds: float = 0.5
    decay_seconds: float = 1.4
    min_amp: float = 0.008
    min_confidence: float = 0.48
    min_velocity: int = 32
    sample_rate: int = 22050
    width: int = 900
    height: int = 190
    demo_mode: bool = False
    demo_midi: str | None = None
    model: str = "piano-gpu"


def parse_args(argv: list[str] | None = None) -> AppConfig:
    parser = argparse.ArgumentParser(
        prog="Piano Shadow",
        description="桌面钢琴音符透明悬浮窗",
    )
    parser.add_argument("--chunk", type=float, default=0.5, help="每次分析的音频秒数")
    parser.add_argument("--decay", type=float, default=1.4, help="高亮衰减秒数")
    parser.add_argument("--min-amp", type=float, default=0.008, help="最低 RMS 音量")
    parser.add_argument("--min-confidence", type=float, default=0.48)
    parser.add_argument("--min-velocity", type=int, default=32)
    parser.add_argument("--sample-rate", type=int, default=22050)
    parser.add_argument("--width", type=int, default=900)
    parser.add_argument("--height", type=int, default=190)
    parser.add_argument("--demo-mode", action="store_true", help="随机和弦演示")
    parser.add_argument(
        "--demo-midi",
        metavar="NOTES",
        help='循环演示 MIDI 音符，例如 "60,64,67;62,65,69"',
    )
    parser.add_argument(
        "--model",
        choices=("basic-pitch", "piano-gpu"),
        default="piano-gpu",
        help="音频识别模型",
    )
    ns = parser.parse_args(argv)
    if not 0.5 <= ns.chunk <= 10:
        parser.error("--chunk 必须在 0.5 到 10 秒之间")
    if not 0.2 <= ns.decay <= 10:
        parser.error("--decay 必须在 0.2 到 10 秒之间")
    if ns.width < 560 or ns.height < 120:
        parser.error("窗口尺寸过小（最小 560x120）")
    return AppConfig(
        chunk_seconds=ns.chunk,
        decay_seconds=ns.decay,
        min_amp=max(0.0, ns.min_amp),
        min_confidence=max(0.0, min(1.0, ns.min_confidence)),
        min_velocity=max(0, min(127, ns.min_velocity)),
        sample_rate=ns.sample_rate,
        width=ns.width,
        height=ns.height,
        demo_mode=ns.demo_mode or bool(ns.demo_midi),
        demo_midi=ns.demo_midi,
        model=ns.model,
    )
