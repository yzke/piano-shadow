"""Frameless translucent desktop overlay and animations."""

from __future__ import annotations

import math
import hashlib
import os
import platform
import threading
import time
import urllib.request
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import (
    QLineF,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QTimer,
    QUrl,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QDesktopServices,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QMouseEvent,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QMenu,
    QProgressDialog,
    QSlider,
    QWidget,
    QWidgetAction,
)

from config import (
    AppConfig,
    PIANO_MODEL_MIN_BYTES,
    PIANO_MODEL_PATH,
    SOUNDFONT_MIN_BYTES,
    SOUNDFONT_PATH,
    SOUNDFONT_SHA256,
    SOUNDFONT_URLS,
)
from erhu_model import ErhuMapper, ErhuState, MAX_POSITION
from note_model import (
    NoteEvent,
    PIANO_HIGH,
    PIANO_LOW,
    is_black_key,
    midi_to_name,
)
from performance import (
    INSTRUMENTS,
    MAJOR_ROOTS,
    MINOR_ROOTS,
    PerformanceController,
)

# Stable pitch-class colors across every octave: C4 and C7, for example,
# always share the same color. Sharps receive their own intermediate hue.
PITCH_COLORS = (
    (247, 105, 137),  # C   soft rose
    (249, 132, 116),  # C#  coral glass
    (246, 164, 101),  # D   apricot
    (244, 191, 103),  # D#  warm amber
    (237, 211, 112),  # E   champagne gold
    (119, 215, 157),  # F   mint
    (89, 210, 184),   # F#  aqua mint
    (91, 198, 221),   # G   ice cyan
    (103, 169, 232),  # G#  clear azure
    (124, 143, 235),  # A   periwinkle
    (165, 123, 226),  # A#  lavender
    (207, 119, 211),  # B   orchid
)
SOLFEGE_NAMES = (
    "Do", "Do♯", "Re", "Re♯", "Mi", "Fa",
    "Fa♯", "Sol", "Sol♯", "La", "La♯", "Si",
)
ERHU_D_JIANPU = (
    "♭7", "7", "1", "♯1", "2", "♯2",
    "3", "4", "♯4", "5", "♯5", "6",
)


@dataclass(slots=True)
class VisualNote:
    midi: int
    born: float
    strength: float
    name: str
    lane: int


@dataclass(slots=True)
class ErhuTrail:
    state: ErhuState
    born: float


class OverlayWindow(QWidget):
    notes_received = pyqtSignal(object)
    status_received = pyqtSignal(str, bool)
    model_selected = pyqtSignal(str)
    model_fallback_received = pyqtSignal(str)
    model_download_required = pyqtSignal(str, str)
    model_download_progress_received = pyqtSignal(int, int)
    model_download_source_received = pyqtSignal(str)
    model_download_finished_received = pyqtSignal(bool, str)
    performance_mode_changed = pyqtSignal(bool)
    visual_mode_changed = pyqtSignal(str)
    performance_note_received = pyqtSignal(int, int)
    performance_answer_received = pyqtSignal(int)
    soundfont_download_progress_received = pyqtSignal(int, int)
    soundfont_download_finished_received = pyqtSignal(bool, str)

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.visual_notes: list[VisualNote] = []
        self._visual_mode = "piano"
        self._erhu_mapper = ErhuMapper()
        self._erhu_state: ErhuState | None = None
        self._erhu_display_position = 0.0
        self._erhu_target_position = 0.0
        self._erhu_trails: list[ErhuTrail] = []
        self._erhu_vertical = False
        self._erhu_history = True
        self._erhu_body = True
        self._erhu_mirrored = False
        self.status_text = "Piano Shadow · Starting…"
        self.status_error = False
        self._drag_offset: QPoint | None = None
        self._native_move = False
        self._always_on_top = True
        self._position_locked = False
        self._keyboard_only = False
        self._performance_mode = False
        self._performance_help = False
        self._performance: PerformanceController | None = None
        self._sound_source = "windows"
        self._instrument_index = 0
        self._ear_playback_generation = 0
        self._ear_feedback_target: tuple[int, ...] = ()
        self._ear_feedback_error: tuple[int, int, int] | None = None
        self._ear_feedback_correct = False
        self._vibrato_phase = 0.0
        self._glide_generation = 0
        self._space_sostenuto = False
        self._click_through = False
        self._model_download_prompt_shown = False
        self._gpu_requirements_confirmed = False
        self._model_download_thread: threading.Thread | None = None
        self._model_download_cancel = threading.Event()
        self._model_download_progress: QProgressDialog | None = None
        self._soundfont_download_thread: threading.Thread | None = None
        self._soundfont_download_cancel = threading.Event()
        self._soundfont_download_progress: QProgressDialog | None = None
        self._opacity = 0.85
        self._active_opacity = 0.85
        self._scale_percent = 100
        self._setup_window()
        self.notes_received.connect(self.add_notes)
        self.status_received.connect(self.set_status)
        self.model_fallback_received.connect(self._handle_model_fallback)
        self.model_download_required.connect(self._show_model_download_dialog)
        self.model_download_progress_received.connect(
            self._update_model_download_progress
        )
        self.model_download_source_received.connect(
            self._update_model_download_source
        )
        self.model_download_finished_received.connect(
            self._finish_model_download
        )
        self.performance_note_received.connect(self._show_performance_note)
        self.performance_answer_received.connect(self._handle_ear_answer)
        self.soundfont_download_progress_received.connect(
            self._update_soundfont_download_progress
        )
        self.soundfont_download_finished_received.connect(
            self._finish_soundfont_download
        )
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)
        self._vibrato_timer = QTimer(self)
        self._vibrato_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._vibrato_timer.setInterval(35)
        self._vibrato_timer.timeout.connect(self._vibrato_tick)

    def _setup_window(self) -> None:
        self.setWindowTitle("Piano Shadow")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setFixedSize(self.config.width, self.config.height)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.width() // 2, screen.bottom() - self.height() - 56)

    def add_notes(self, events: list[NoteEvent]) -> None:
        """Replay a transcribed chunk in onset order, preserving chords."""
        if not events or self._performance_mode:
            return
        ordered = sorted(events, key=lambda event: (event.start, event.midi))
        groups: list[list[NoteEvent]] = []
        group_start = ordered[0].start
        for event in ordered:
            if not groups or event.start - group_start > 0.06:
                groups.append([event])
                group_start = event.start
            else:
                groups[-1].append(event)

        first_start = groups[0][0].start
        for group in groups:
            # Keep natural timing but cap malformed/model-padded timestamps.
            delay_ms = round(min(0.65, max(0.0, group[0].start - first_start)) * 1000)
            if delay_ms == 0:
                self._display_notes(group)
            else:
                QTimer.singleShot(
                    delay_ms,
                    lambda pending=list(group): self._display_notes(pending),
                )

    def _display_notes(self, events: list[NoteEvent]) -> None:
        if self._visual_mode == "erhu":
            self._display_erhu_note(events)
            return
        now = time.monotonic()
        # Show the strongest recent occurrence once per pitch.
        strongest: dict[int, NoteEvent] = {}
        for event in events:
            if event.midi not in strongest or event.confidence > strongest[event.midi].confidence:
                strongest[event.midi] = event
        for lane, event in enumerate(sorted(strongest.values(), key=lambda n: n.midi)):
            self.visual_notes.append(
                VisualNote(
                    event.midi,
                    now,
                    max(0.4, event.velocity / 127),
                    event.name,
                    lane,
                )
            )
        self.visual_notes = self.visual_notes[-40:]
        self.update()

    def _display_erhu_note(self, events: list[NoteEvent]) -> None:
        if not events:
            return
        # Erhu Shadow deliberately follows one melody note, not a chord.
        event = max(events, key=lambda item: (item.confidence, item.velocity))
        state = self._erhu_mapper.map(event.midi, event.confidence)
        if state is None:
            return
        now = time.monotonic()
        if self._erhu_state is None or self._erhu_state.string_name != state.string_name:
            self._erhu_display_position = float(state.position)
        self._erhu_state = state
        self._erhu_target_position = float(state.position)
        self._erhu_trails.append(ErhuTrail(state, now))
        self._erhu_trails = self._erhu_trails[-12:]
        self.update()

    def set_status(self, text: str, error: bool = False) -> None:
        self.status_text = text
        self.status_error = error
        self.update()

    def _tick(self) -> None:
        now = time.monotonic()
        self.visual_notes = [
            n for n in self.visual_notes if now - n.born < self.config.decay_seconds * 1.35
        ]
        erhu_trail_seconds = max(5.5, self.config.decay_seconds * 3.8)
        self._erhu_trails = [
            trail for trail in self._erhu_trails if now - trail.born < erhu_trail_seconds
        ]
        distance = self._erhu_target_position - self._erhu_display_position
        if abs(distance) > 0.01:
            # Frame-rate-independent-looking easing, fast enough to cross
            # several positions while still reading as discrete movement.
            self._erhu_display_position += distance * 0.22
        else:
            self._erhu_display_position = self._erhu_target_position
        if self.visual_notes or self._erhu_trails or abs(distance) > 0.01:
            self.update()

    def _alpha(self, note: VisualNote, now: float) -> float:
        age = now - note.born
        fade_in = min(1.0, age / 0.12)
        return fade_in * math.exp(-3.0 * age / self.config.decay_seconds)

    @staticmethod
    def _note_color(midi: int, alpha: int = 255) -> QColor:
        red, green, blue = PITCH_COLORS[midi % 12]
        color = QColor(red, green, blue)
        hue, saturation, lightness, _ = color.getHslF()
        # Keep pitch-class identity while adding a restrained register cue:
        # bass is slightly duskier, treble slightly clearer. The full piano
        # range shifts only about ±10% in HSL lightness.
        register = max(-1.0, min(1.0, (midi - 60) / 48.0))
        lightness = max(0.0, min(1.0, lightness + register * 0.10))
        saturation = max(0.0, min(1.0, saturation + register * 0.025))
        color.setHslF(hue, saturation, lightness, max(0, min(255, alpha)) / 255)
        return color

    @classmethod
    def _erhu_note_color(
        cls,
        midi: int,
        string_name: str,
        alpha: int = 255,
    ) -> QColor:
        """Preserve pitch hue while distinguishing lower/upper erhu strings."""
        color = cls._note_color(midi, alpha)
        hue, saturation, lightness, opacity = color.getHslF()
        offset = 0.065 if string_name == "outer" else -0.055
        color.setHslF(
            hue,
            saturation,
            max(0.0, min(1.0, lightness + offset)),
            opacity,
        )
        return color

    @staticmethod
    def _erhu_history_alpha(index: int) -> int:
        """Newest historical erhu note is half opacity; each older note halves again."""
        if index < 0:
            return 0
        return max(0, min(255, round(128 * (0.5**index))))

    @staticmethod
    def _erhu_history_diameter(index: int) -> float:
        if index < 0:
            return 0.0
        return max(9.0, 13.5 - index * 0.75)

    def _keyboard_geometry(self) -> tuple[dict[int, QRectF], dict[int, QRectF]]:
        margin = 20.0
        top = self.height() * 0.58
        height = self.height() - top - 13
        white_notes = [m for m in range(PIANO_LOW, PIANO_HIGH + 1) if not is_black_key(m)]
        white_width = (self.width() - margin * 2) / len(white_notes)
        white: dict[int, QRectF] = {}
        black: dict[int, QRectF] = {}
        white_index = 0
        for midi in range(PIANO_LOW, PIANO_HIGH + 1):
            if is_black_key(midi):
                x = margin + white_index * white_width - white_width * 0.31
                black[midi] = QRectF(x, top, white_width * 0.62, height * 0.61)
            else:
                white[midi] = QRectF(
                    margin + white_index * white_width, top, white_width + 0.05, height
                )
                white_index += 1
        return white, black

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        now = time.monotonic()
        if not self._keyboard_only:
            self._draw_glass(painter)
            self._draw_status(painter)
        if self._performance_mode:
            self._draw_performance_status(painter)
            self._draw_ear_feedback(painter)
        if self._visual_mode == "piano":
            self._draw_pitch_legend(painter)
        else:
            self._draw_erhu_legend(painter)
        self._draw_controls(painter)
        if self._visual_mode == "erhu":
            self._draw_erhu(painter, now)
        else:
            white, black = self._keyboard_geometry()
            self._draw_note_labels(painter, now, white, black)
            self._draw_keyboard(painter, white, black, now)

    def _draw_glass(self, p: QPainter) -> None:
        p.save()
        p.setOpacity(self._opacity)
        panel = QRectF(7, 7, self.width() - 14, self.height() - 14)
        path = QPainterPath()
        path.addRoundedRect(panel, 22, 22)
        gradient = QLinearGradient(0, 0, 0, self.height())
        # At 100% control opacity the glass is almost solid (~90% alpha).
        # The painter-level opacity scales this consistently on WSL/Wayland.
        gradient.setColorAt(0, QColor(16, 22, 34, 220))
        gradient.setColorAt(1, QColor(5, 9, 17, 205))
        p.fillPath(path, gradient)
        p.setPen(QPen(QColor(255, 255, 255, 25), 1))
        p.drawPath(path)
        p.restore()

    def _draw_status(self, p: QPainter) -> None:
        font = QFont("Inter, Noto Sans CJK SC, sans-serif", 9)
        font.setWeight(QFont.Weight.Medium)
        p.setFont(font)
        metrics = QFontMetricsF(font)
        text = self.status_text
        max_width = self.width() * 0.52
        text = metrics.elidedText(text, Qt.TextElideMode.ElideRight, max_width)
        pill = QRectF(21, 16, metrics.horizontalAdvance(text) + 29, 27)
        color = QColor(255, 174, 185, 215) if self.status_error else QColor(191, 230, 255, 215)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(18, 27, 42, 166))
        p.drawRoundedRect(pill, 13.5, 13.5)
        p.setPen(QPen(color))
        p.drawText(pill.adjusted(14, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter, text)

    def _draw_pitch_legend(self, p: QPainter) -> None:
        controls = self._control_rects()
        control_left = min(rect.left() for rect in controls.values())
        names = ("Do", "Re", "Mi", "Fa", "Sol", "La", "Si")
        pitch_classes = (0, 2, 4, 5, 7, 9, 11)
        gap = 3.0
        item_width = max(14.0, min(20.0, self.width() * 0.021))
        total_width = len(names) * item_width + (len(names) - 1) * gap
        start_x = control_left - total_width - 12
        if start_x < 8:
            return

        p.save()
        p.setOpacity(self._active_opacity)
        font = QFont("Inter, Arial, sans-serif", max(7, round(self.height() * 0.050)))
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        for index, (name, pitch_class) in enumerate(zip(names, pitch_classes)):
            x = start_x + index * (item_width + gap)
            red, green, blue = PITCH_COLORS[pitch_class]
            color = QColor(red, green, blue, 220)
            label_rect = QRectF(x - 1, 17, item_width + 2, 20)
            p.setPen(color)
            p.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, name)
        p.restore()

    def _draw_erhu_legend(self, p: QPainter) -> None:
        degrees = ("1", "2", "3", "4", "5", "6", "7")
        pitch_classes = (2, 4, 6, 7, 9, 11, 1)  # D major
        p.save()
        p.setOpacity(self._active_opacity)
        font = QFont(
            "Inter, Noto Sans CJK SC, sans-serif",
            max(7, round(min(self.width(), self.height()) * 0.046)),
        )
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        if self._erhu_vertical:
            x = 17.0
            start_y = max(315.0, self.height() * 0.36)
            for index, (degree, pitch_class) in enumerate(
                zip(degrees, pitch_classes)
            ):
                rect = QRectF(x, start_y + index * 27.0, 22, 20)
                p.setPen(self._note_color(60 + pitch_class, 230))
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, degree)
        else:
            controls = self._control_rects()
            control_left = min(rect.left() for rect in controls.values())
            item_width = 20.0
            gap = 4.0
            total = len(degrees) * item_width + (len(degrees) - 1) * gap
            start_x = control_left - total - 12.0
            if start_x >= 8:
                for index, (degree, pitch_class) in enumerate(
                    zip(degrees, pitch_classes)
                ):
                    rect = QRectF(
                        start_x + index * (item_width + gap),
                        17,
                        item_width,
                        20,
                    )
                    p.setPen(self._note_color(60 + pitch_class, 230))
                    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, degree)
        p.restore()

    def _draw_erhu_body(
        self,
        p: QPainter,
        *,
        vertical: bool,
        left: float | None = None,
        right: float | None = None,
        bottom: float | None = None,
        string_axis: dict[str, float],
    ) -> None:
        """Draw a subtle rounded resonator hint behind the erhu strings."""
        rect = self._erhu_body_rect(
            vertical=vertical,
            left=left,
            right=right,
            bottom=bottom,
            string_axis=string_axis,
        )
        if vertical:
            highlight = QLineF(
                rect.left() + 16.0,
                rect.top() + 12.0,
                rect.right() - 16.0,
                rect.top() + 12.0,
            )
            inner_line = QLineF(
                rect.left() + 20.0,
                rect.bottom() - 12.0,
                rect.right() - 20.0,
                rect.bottom() - 12.0,
            )
        else:
            highlight = QLineF(
                rect.left() + 20.0,
                rect.top() + 12.0,
                rect.right() - 20.0,
                rect.top() + 12.0,
            )
            inner_line = QLineF(
                rect.left() + 24.0,
                rect.bottom() - 12.0,
                rect.right() - 24.0,
                rect.bottom() - 12.0,
            )

        radius = min(rect.width(), rect.height()) * 0.32
        body = QPainterPath()
        body.addRoundedRect(rect, radius, radius)
        fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
        fill.setColorAt(0.0, QColor(205, 139, 76, 128))
        fill.setColorAt(0.42, QColor(126, 72, 38, 150))
        fill.setColorAt(1.0, QColor(46, 24, 15, 180))

        p.save()
        p.setOpacity(max(0.78, self._opacity * 0.98))
        p.setPen(QPen(QColor(25, 10, 4, 122), 3.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(body)
        p.setPen(QPen(QColor(244, 188, 118, 132), 1.1))
        p.setBrush(fill)
        p.drawPath(body)
        p.setPen(QPen(QColor(255, 218, 156, 112), 0.9))
        p.drawLine(highlight)
        p.setPen(QPen(QColor(28, 11, 5, 122), 0.95))
        p.drawLine(inner_line)
        p.restore()

    def _draw_erhu_top_bars(
        self,
        p: QPainter,
        *,
        top: float,
        string_axis: dict[str, float],
    ) -> None:
        """Draw the two subtle upper erhu pegs/bars in vertical mode."""
        bars = self._erhu_top_bar_rects(
            top=top,
            string_axis=string_axis,
            mirrored=self._erhu_mirrored,
        )

        p.save()
        p.setOpacity(max(0.74, self._opacity * 0.94))
        for index, rect in enumerate(bars):
            fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
            fill.setColorAt(0.0, QColor(218, 150, 82, 118 - index * 10))
            fill.setColorAt(0.45, QColor(129, 73, 38, 142 - index * 10))
            fill.setColorAt(1.0, QColor(47, 24, 13, 170 - index * 10))
            wide = rect.height()
            narrow = max(4.2, rect.height() * 0.58)
            left_height = narrow if self._erhu_mirrored else wide
            right_height = wide if self._erhu_mirrored else narrow
            left_mid = rect.center().y()
            right_mid = rect.center().y()
            shape = QPainterPath()
            shape.moveTo(rect.left(), left_mid - left_height / 2)
            shape.lineTo(rect.right(), right_mid - right_height / 2)
            shape.lineTo(rect.right(), right_mid + right_height / 2)
            shape.lineTo(rect.left(), left_mid + left_height / 2)
            shape.closeSubpath()
            p.setPen(QPen(QColor(26, 10, 4, 112), 2.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(shape)
            p.setPen(QPen(QColor(244, 190, 116, 118), 0.85))
            p.setBrush(fill)
            p.drawPath(shape)
            p.setPen(QPen(QColor(255, 224, 166, 86), 0.7))
            p.drawLine(
                QLineF(
                    rect.left() + 10.0,
                    rect.center().y() - left_height * 0.20,
                    rect.right() - 10.0,
                    rect.center().y() - right_height * 0.20,
                )
            )
        p.restore()

    @staticmethod
    def _erhu_top_bar_rects(
        *,
        top: float,
        string_axis: dict[str, float],
        mirrored: bool = False,
    ) -> tuple[QRectF, QRectF]:
        inner_axis = string_axis["inner"]
        outer_axis = string_axis["outer"]
        low = min(inner_axis, outer_axis)
        high = max(inner_axis, outer_axis)
        long_side = 48.0
        short_side = 24.0
        left = low - (short_side if mirrored else long_side)
        right = high + (long_side if mirrored else short_side)
        width = right - left
        return (
            QRectF(left, top + 8.0, width, 8.5),
            QRectF(left + 9.0, top + 46.0, width - 18.0, 7.5),
        )

    def _erhu_vertical_string_axis(self) -> dict[str, float]:
        if self._erhu_body:
            inner_x = self.width() * 0.49
            outer_x = self.width() * 0.62
            normal_center = (inner_x + outer_x) / 2
            # Keep the resonator fixed as the visual anchor. In the default
            # view the string pair sits slightly right of the resonator center;
            # mirror mode places the pair the same distance to the left.
            body_left = inner_x - 74.0
            body_width = outer_x - inner_x + 74.0 + 26.0
            body_center = body_left + body_width / 2
            mirrored_center = body_center - (normal_center - body_center)
            string_gap = outer_x - inner_x
            mirrored_outer_x = mirrored_center - string_gap / 2
            mirrored_inner_x = mirrored_center + string_gap / 2
        else:
            inner_x = self.width() * 0.36
            outer_x = self.width() * 0.62
            mirrored_inner_x = outer_x
            mirrored_outer_x = inner_x
        if self._erhu_mirrored:
            return {"inner": mirrored_inner_x, "outer": mirrored_outer_x}
        return {"inner": inner_x, "outer": outer_x}

    def _erhu_horizontal_string_axis(self) -> dict[str, float]:
        normal_axis = {
            "inner": self.height() * 0.58,
            "outer": self.height() * 0.75,
        }
        if self._erhu_mirrored:
            return {"inner": normal_axis["outer"], "outer": normal_axis["inner"]}
        return normal_axis

    def _erhu_vertical_label_rects(
        self,
        *,
        top: float,
        string_axis: dict[str, float],
    ) -> dict[str, QRectF]:
        label_width = min(108.0, max(78.0, self.width() * 0.25))
        margin = 6.0
        label_y = top - 23.0

        def rect_for(axis: float) -> QRectF:
            left = max(
                margin,
                min(self.width() - label_width - margin, axis - label_width / 2),
            )
            return QRectF(left, label_y, label_width, 18.0)

        inner = rect_for(string_axis["inner"])
        outer = rect_for(string_axis["outer"])
        if inner.intersects(outer.adjusted(-4, 0, 4, 0)):
            ordered = sorted(
                ("inner", "outer"),
                key=lambda name: string_axis[name],
            )
            gap = 4.0
            left_rect = QRectF(
                max(margin, min(inner.left(), outer.left())),
                label_y,
                label_width,
                18.0,
            )
            right_rect = QRectF(
                min(
                    self.width() - label_width - margin,
                    left_rect.right() + gap,
                ),
                label_y,
                label_width,
                18.0,
            )
            if right_rect.left() <= left_rect.right():
                left_rect.moveLeft(max(margin, right_rect.left() - label_width - gap))
            return {ordered[0]: left_rect, ordered[1]: right_rect}
        return {"inner": inner, "outer": outer}

    def _erhu_body_rect(
        self,
        *,
        vertical: bool,
        left: float | None = None,
        right: float | None = None,
        bottom: float | None = None,
        string_axis: dict[str, float],
    ) -> QRectF:
        """Geometry for the erhu resonator, aligned from the string axes."""
        if vertical:
            if self._erhu_body:
                # Keep the resonator as the visual anchor. Mirror mode moves
                # strings/pegs around it; the body itself should not drift.
                inner_axis = self.width() * 0.49
                outer_axis = self.width() * 0.62
            else:
                inner_axis = string_axis["inner"]
                outer_axis = string_axis["outer"]
            left_padding = 74.0
            right_padding = 26.0
            low = min(inner_axis, outer_axis)
            high = max(inner_axis, outer_axis)
            body_width = abs(high - low) + left_padding + right_padding
            body_height = 70.0
            rect_left = low - left_padding
            rect_top = (bottom or self.height()) - body_height + 5.0
            return QRectF(rect_left, rect_top, body_width, body_height)

        inner_axis = string_axis["inner"]
        outer_axis = string_axis["outer"]
        padding_y = 16.0
        body_width = 134.0
        body_height = abs(outer_axis - inner_axis) + padding_y * 2
        rect_left = (right or self.width()) - body_width - 18.0
        rect_top = min(inner_axis, outer_axis) - padding_y
        return QRectF(rect_left, rect_top, body_width, body_height)

    def _control_rects(self) -> dict[str, QRectF]:
        size = max(21.0, min(27.0, self.height() * 0.17))
        gap = 5.0
        if self._keyboard_only:
            return {"lock": QRectF(self.width() - 20.0 - size, 16.0, size, size)}
        primary = (
            "visual_mode",
            "minimal",
            "lock",
            "top",
            "smaller",
            "larger",
            "keyboard_opacity",
            "active_opacity",
        )
        if self._visual_mode == "erhu" and self._erhu_vertical:
            x = self.width() - 16.0 - size
            controls = {
                name: QRectF(x, 16.0 + index * (size + gap), size, size)
                for index, name in enumerate(primary)
            }
            controls["erhu_rotate"] = QRectF(
                x, 16.0 + len(primary) * (size + gap), size, size
            )
            controls["erhu_history"] = QRectF(
                x, 16.0 + (len(primary) + 1) * (size + gap), size, size
            )
            controls["erhu_body"] = QRectF(
                x, 16.0 + (len(primary) + 2) * (size + gap), size, size
            )
            controls["erhu_mirror"] = QRectF(
                x, 16.0 + (len(primary) + 3) * (size + gap), size, size
            )
            return controls
        start = self.width() - 20.0 - len(primary) * size - (len(primary) - 1) * gap
        controls = {
            name: QRectF(start + index * (size + gap), 16.0, size, size)
            for index, name in enumerate(primary)
        }
        secondary: tuple[tuple[str, float], ...]
        if self._visual_mode == "erhu":
            secondary = (
                ("erhu_rotate", size),
                ("erhu_history", size),
                ("erhu_body", size),
                ("erhu_mirror", size),
            )
        else:
            secondary = (
                ("performance", size),
                ("piano_model", size),
            )
        if self._performance_mode:
            secondary += (
                ("input_mode", size),
                ("performance_help", size),
                ("ear_training", size),
                ("instrument_prev", size),
                ("instrument_label", max(94.0, size * 3.7)),
                ("instrument_next", size),
                ("instrument_reset", size),
                ("soundfont_manage", size),
            )
        if secondary:
            total_width = (
                sum(width for _name, width in secondary)
                + (len(secondary) - 1) * gap
            )
            x = self.width() - 20.0 - total_width
            for name, width in secondary:
                controls[name] = QRectF(
                    x, 16.0 + size + gap, width, size
                )
                x += width + gap
        return controls

    def _draw_performance_status(self, p: QPainter) -> None:
        if self._performance is None:
            return
        controller = self._performance
        roots = MAJOR_ROOTS if controller.mode == "major" else MINOR_ROOTS
        tonic = roots[controller.scale_index]
        color = self._note_color(60 + tonic, 245)
        p.save()
        p.setOpacity(self._active_opacity)
        title_font = QFont(
            "Inter, Noto Sans CJK SC, sans-serif",
            max(10, round(self.height() * 0.072)),
        )
        title_font.setWeight(QFont.Weight.DemiBold)
        p.setFont(title_font)
        p.setPen(color)
        p.drawText(
            QRectF(24, 43, 230, 23),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"当前 · {controller.scale_name}",
        )
        if self._performance_help:
            help_rect = QRectF(
                self.width() * 0.18,
                58,
                self.width() * 0.64,
                48,
            )
            p.setPen(QPen(QColor(255, 255, 255, 22), 0.8))
            p.setBrush(QColor(8, 14, 24, 205))
            p.drawRoundedRect(help_rect, 10, 10)
            p.setFont(QFont("Inter, Noto Sans CJK SC, sans-serif", 7))
            p.setPen(QColor(210, 225, 239, 205))
            p.drawText(
                help_rect.adjusted(10, 4, -10, -4),
                Qt.AlignmentFlag.AlignCenter,
                self._performance_help_text(controller),
            )
        p.restore()

    @staticmethod
    def _performance_help_text(controller: PerformanceController) -> str:
        common = "Shift/Ctrl 升降半音 · ←→ 五度圈 · ↑↓ 八度"
        profile = controller.technique_profile
        if profile == "piano":
            return (
                "钢琴踏板：Space 延音 · Alt 弱音 · Alt+Space 选择性延音\n"
                "选择性延音仅保持组合键按下时已经发声的音\n"
                f"{common} · Enter 休止"
            )
        if profile == "organ":
            return (
                "风琴：按住 Alt 加速 Leslie/调制，松开恢复\n"
                "风琴不模拟钢琴延音踏板\n"
                f"{common} · Enter 休止"
            )
        if profile == "guitar":
            return (
                "吉他/贝斯：保持当前音，Alt+目标音 滑弦/推弦（一个八度内）\n"
                "Space 延音 · Enter 休止\n"
                f"{common}"
            )
        if profile in {"strings", "winds", "synth"}:
            technique = {
                "strings": "弦乐/二胡",
                "winds": "管乐",
                "synth": "合成器",
            }[profile]
            return (
                f"{technique}：Space 揉弦/颤音，松开回正\n"
                "保持当前音，按住左/右 Alt 再按目标音滑音（一个八度内）\n"
                f"{common} · Enter 休止"
            )
        return (
            "每排前 7 键为一组音阶，右侧按键顺延至高八度\n"
            "Space 延音 · Enter 休止\n"
            f"{common}"
        )

    def _draw_ear_feedback(self, p: QPainter) -> None:
        if not self._ear_feedback_target:
            return
        target = self._ear_feedback_target
        error = self._ear_feedback_error
        width = min(self.width() * 0.58, 58.0 + len(target) * 58.0)
        panel = QRectF((self.width() - width) / 2, 48, width, 55)
        p.save()
        p.setOpacity(self._active_opacity)
        p.setPen(QPen(QColor(255, 255, 255, 28), 0.8))
        p.setBrush(QColor(8, 14, 24, 218))
        p.drawRoundedRect(panel, 12, 12)

        title_font = QFont(
            "Inter, Noto Sans CJK SC, sans-serif",
            max(7, round(self.height() * 0.043)),
        )
        title_font.setWeight(QFont.Weight.DemiBold)
        p.setFont(title_font)
        if error is None:
            p.setPen(QColor(157, 230, 190, 225))
            title = "正确 · 完整答案"
        else:
            index, expected, actual = error
            p.setPen(QColor(255, 130, 140, 235))
            title = (
                f"第 {index + 1} 音错误："
                f"{midi_to_name(actual)} → {midi_to_name(expected)}"
            )
        p.drawText(
            QRectF(panel.left() + 10, panel.top() + 3, panel.width() - 20, 17),
            Qt.AlignmentFlag.AlignCenter,
            title,
        )

        item_width = min(52.0, (panel.width() - 20) / len(target))
        row_width = item_width * len(target)
        start_x = panel.center().x() - row_width / 2
        note_font = QFont("Inter, Arial, sans-serif", max(7, round(self.height() * 0.047)))
        note_font.setWeight(QFont.Weight.DemiBold)
        solfege_font = QFont("Inter, Arial, sans-serif", max(6, round(self.height() * 0.037)))
        for item_index, midi in enumerate(target):
            item = QRectF(start_x + item_index * item_width, panel.top() + 20, item_width, 31)
            is_error = error is not None and item_index == error[0]
            display_midi = error[2] if is_error else midi
            color = (
                QColor(255, 92, 108, 245)
                if is_error
                else self._note_color(midi, 235)
            )
            if is_error:
                p.setPen(QPen(QColor(255, 92, 108, 135), 0.9))
                p.setBrush(QColor(118, 24, 37, 80))
                p.drawRoundedRect(item.adjusted(3, 0, -3, 0), 6, 6)
            p.setPen(color)
            p.setFont(note_font)
            p.drawText(
                QRectF(item.left(), item.top(), item.width(), 16),
                Qt.AlignmentFlag.AlignCenter,
                midi_to_name(display_midi),
            )
            p.setFont(solfege_font)
            if is_error:
                p.setPen(self._note_color(midi, 235))
                solfege = f"→ {midi_to_name(midi)} {SOLFEGE_NAMES[midi % 12]}"
            else:
                solfege = SOLFEGE_NAMES[display_midi % 12]
            p.drawText(
                QRectF(item.left(), item.top() + 15, item.width(), 14),
                Qt.AlignmentFlag.AlignCenter,
                solfege,
            )
        p.restore()

    def _draw_controls(self, p: QPainter) -> None:
        p.save()
        for name, rect in self._control_rects().items():
            p.save()
            enabled = self._control_enabled(name)
            active = (
                (name == "lock" and self._position_locked)
                or (name == "top" and self._always_on_top)
                or (name == "piano_model" and self.config.model == "piano-gpu")
                or (name == "erhu_rotate" and self._erhu_vertical)
                or (name == "erhu_history" and self._erhu_history)
                or (name == "erhu_body" and self._erhu_body)
                or (name == "erhu_mirror" and self._erhu_mirrored)
                or (name == "visual_mode" and self._visual_mode == "erhu")
                or (name == "performance_help" and self._performance_help)
                or (
                    name == "ear_training"
                    and self._performance is not None
                    and self._performance.ear_training.note_count > 0
                )
                or (
                    name == "input_mode"
                    and self._performance is not None
                    and self._performance.input_mode == "midi"
                )
                or (
                    name == "instrument_label"
                    and self._performance is not None
                    and self._performance.sound_source == "soundfont"
                )
            )
            if enabled:
                p.setPen(QPen(QColor(132, 208, 246, 105) if active else QColor(255, 255, 255, 25)))
                p.setBrush(QColor(61, 139, 186, 90) if active else QColor(19, 29, 45, 155))
            else:
                p.setPen(QPen(QColor(255, 255, 255, 18)))
                p.setBrush(QColor(13, 20, 31, 92))
            p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
            if not enabled:
                p.setOpacity(0.45)
            self._draw_control_icon(p, name, rect)
            p.restore()
        p.restore()

    def _control_enabled(self, name: str) -> bool:
        if name == "erhu_body":
            return self._visual_mode == "erhu" and self._erhu_vertical
        if name == "erhu_mirror":
            return self._visual_mode == "erhu"
        return True

    def _draw_control_icon(self, p: QPainter, name: str, rect: QRectF) -> None:
        cx, cy = rect.center().x(), rect.center().y()
        unit = rect.width() / 8.0
        p.setPen(QPen(QColor(205, 233, 249, 225), max(1.2, unit * 0.48)))
        p.setBrush(Qt.BrushStyle.NoBrush)

        if name == "minimal":
            # Four focus corners: remove all chrome and keep only the keyboard.
            corner = unit * 2.0
            short = unit * 1.15
            for x, y, dx, dy in (
                (cx - corner, cy - corner, 1, 1),
                (cx + corner, cy - corner, -1, 1),
                (cx - corner, cy + corner, 1, -1),
                (cx + corner, cy + corner, -1, -1),
            ):
                p.drawLine(QLineF(x, y, x + dx * short, y))
                p.drawLine(QLineF(x, y, x, y + dy * short))
        elif name == "performance":
            for offset in (-1.65, 0, 1.65):
                key = QRectF(
                    cx + offset * unit - 0.7 * unit,
                    cy - 2.25 * unit,
                    1.4 * unit,
                    4.5 * unit,
                )
                p.drawRoundedRect(key, unit * 0.25, unit * 0.25)
            p.drawLine(
                QLineF(cx - 2.45 * unit, cy + 2.35 * unit, cx + 2.45 * unit, cy + 2.35 * unit)
            )
        elif name == "visual_mode":
            font = QFont(
                "Inter, Noto Sans CJK SC, sans-serif",
                max(8, round(unit * 2.25)),
            )
            font.setWeight(QFont.Weight.Bold)
            p.setFont(font)
            p.drawText(
                rect,
                Qt.AlignmentFlag.AlignCenter,
                "胡" if self._visual_mode == "erhu" else "钢",
            )
        elif name == "performance_help":
            font = QFont("Inter, Arial, sans-serif", max(8, round(unit * 2.4)))
            font.setWeight(QFont.Weight.Bold)
            p.setFont(font)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "?")
        elif name == "ear_training":
            level = (
                self._performance.ear_training.note_count
                if self._performance is not None
                else 0
            )
            p.drawEllipse(QRectF(cx - 2.2 * unit, cy - 1.2 * unit, 1.5 * unit, 1.5 * unit))
            p.drawLine(QLineF(cx - 0.7 * unit, cy - 0.5 * unit, cx - 0.7 * unit, cy - 2.5 * unit))
            p.drawLine(QLineF(cx - 0.7 * unit, cy - 2.5 * unit, cx + 1.0 * unit, cy - 2.0 * unit))
            font = QFont("Inter, Arial, sans-serif", max(7, round(unit * 2.0)))
            font.setWeight(QFont.Weight.Bold)
            p.setFont(font)
            p.drawText(
                QRectF(cx - 0.1 * unit, cy - 0.1 * unit, 3.0 * unit, 2.7 * unit),
                Qt.AlignmentFlag.AlignCenter,
                str(level) if level else "×",
            )
        elif name == "instrument_label":
            font = QFont(
                "Inter, Noto Sans CJK SC, sans-serif",
                max(7, round(rect.height() * 0.31)),
            )
            font.setWeight(QFont.Weight.DemiBold)
            p.setFont(font)
            text = (
                self._performance.sound_label
                if self._performance is not None
                else "WIN · 大钢琴"
            )
            p.drawText(
                rect.adjusted(7, 0, -7, 0),
                Qt.AlignmentFlag.AlignCenter,
                text,
            )
        elif name in {"instrument_prev", "instrument_next"}:
            direction = -1 if name == "instrument_prev" else 1
            p.drawLine(
                QLineF(
                    cx - direction * 0.9 * unit,
                    cy - 1.7 * unit,
                    cx + direction * 0.9 * unit,
                    cy,
                )
            )
            p.drawLine(
                QLineF(
                    cx + direction * 0.9 * unit,
                    cy,
                    cx - direction * 0.9 * unit,
                    cy + 1.7 * unit,
                )
            )
        elif name == "instrument_reset":
            arc = QRectF(
                cx - 2.0 * unit,
                cy - 2.0 * unit,
                4.0 * unit,
                4.0 * unit,
            )
            p.drawArc(arc, 35 * 16, 285 * 16)
            p.drawLine(
                QLineF(
                    cx - 2.0 * unit,
                    cy - 0.2 * unit,
                    cx - 2.5 * unit,
                    cy - 1.5 * unit,
                )
            )
            p.drawLine(
                QLineF(
                    cx - 2.0 * unit,
                    cy - 0.2 * unit,
                    cx - 0.7 * unit,
                    cy - 0.7 * unit,
                )
            )
        elif name == "soundfont_manage":
            p.drawLine(QLineF(cx, cy - 2.5 * unit, cx, cy + 0.8 * unit))
            p.drawLine(QLineF(cx, cy + 0.8 * unit, cx - 1.2 * unit, cy - 0.4 * unit))
            p.drawLine(QLineF(cx, cy + 0.8 * unit, cx + 1.2 * unit, cy - 0.4 * unit))
            p.drawRoundedRect(
                QRectF(cx - 2.2 * unit, cy + 1.2 * unit, 4.4 * unit, 1.3 * unit),
                0.35 * unit,
                0.35 * unit,
            )
        elif name == "input_mode":
            if self._performance and self._performance.input_mode == "midi":
                p.drawEllipse(
                    QRectF(cx - 1.5 * unit, cy - 1.8 * unit, 3.0 * unit, 3.0 * unit)
                )
                for offset in (-0.8, 0, 0.8):
                    p.drawPoint(QPoint(round(cx + offset * unit), round(cy - 0.4 * unit)))
                p.drawLine(QLineF(cx, cy + 1.2 * unit, cx, cy + 2.2 * unit))
            else:
                p.drawRoundedRect(
                    QRectF(cx - 2.4 * unit, cy - 1.6 * unit, 4.8 * unit, 3.2 * unit),
                    unit * 0.35,
                    unit * 0.35,
                )
                p.drawLine(QLineF(cx - 1.6 * unit, cy + 0.4 * unit, cx + 1.6 * unit, cy + 0.4 * unit))
        elif name == "piano_model":
            chip = QRectF(cx - 2.15 * unit, cy - 1.75 * unit, 4.3 * unit, 3.5 * unit)
            p.drawRoundedRect(chip, unit * 0.45, unit * 0.45)
            for offset in (-1.25, 0, 1.25):
                p.drawLine(QLineF(cx + offset * unit, cy - 2.45 * unit, cx + offset * unit, cy - 1.75 * unit))
                p.drawLine(QLineF(cx + offset * unit, cy + 1.75 * unit, cx + offset * unit, cy + 2.45 * unit))
        elif name == "erhu_rotate":
            p.drawLine(
                QLineF(cx - 2.2 * unit, cy - 1.5 * unit, cx + 1.7 * unit, cy - 1.5 * unit)
            )
            p.drawLine(
                QLineF(cx + 1.7 * unit, cy - 1.5 * unit, cx + 1.7 * unit, cy + 1.2 * unit)
            )
            p.drawLine(
                QLineF(cx + 1.7 * unit, cy + 1.2 * unit, cx + 0.5 * unit, cy + 0.1 * unit)
            )
            p.drawLine(
                QLineF(cx + 1.7 * unit, cy + 1.2 * unit, cx + 2.7 * unit, cy + 0.1 * unit)
            )
        elif name == "erhu_history":
            for index, radius in enumerate((0.7, 1.15, 1.6)):
                color = QColor(205, 233, 249, 225 - index * 62)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(color)
                x = cx - 1.7 * unit + index * 1.7 * unit
                p.drawEllipse(
                    QRectF(
                        x - radius * unit / 2,
                        cy - radius * unit / 2,
                        radius * unit,
                        radius * unit,
                    )
                )
        elif name == "erhu_body":
            body = QRectF(cx - 2.25 * unit, cy - 1.65 * unit, 4.5 * unit, 3.3 * unit)
            p.setPen(QPen(QColor(205, 233, 249, 220), max(1.0, unit * 0.38)))
            p.setBrush(QColor(205, 233, 249, 35))
            p.drawRoundedRect(body, 0.75 * unit, 0.75 * unit)
            p.drawLine(QLineF(cx - 1.35 * unit, cy - 0.45 * unit, cx + 1.35 * unit, cy - 0.45 * unit))
            p.drawLine(QLineF(cx - 1.0 * unit, cy + 0.55 * unit, cx + 1.0 * unit, cy + 0.55 * unit))
        elif name == "erhu_mirror":
            p.drawLine(QLineF(cx, cy - 2.5 * unit, cx, cy + 2.5 * unit))
            p.drawLine(QLineF(cx - 2.6 * unit, cy - 1.0 * unit, cx - 0.55 * unit, cy - 1.0 * unit))
            p.drawLine(QLineF(cx - 2.6 * unit, cy + 1.0 * unit, cx - 0.55 * unit, cy + 1.0 * unit))
            p.drawLine(QLineF(cx + 0.55 * unit, cy - 1.0 * unit, cx + 2.6 * unit, cy - 1.0 * unit))
            p.drawLine(QLineF(cx + 0.55 * unit, cy + 1.0 * unit, cx + 2.6 * unit, cy + 1.0 * unit))
            p.drawLine(QLineF(cx - 2.6 * unit, cy - 1.0 * unit, cx - 1.8 * unit, cy - 1.8 * unit))
            p.drawLine(QLineF(cx - 2.6 * unit, cy - 1.0 * unit, cx - 1.8 * unit, cy - 0.2 * unit))
            p.drawLine(QLineF(cx + 2.6 * unit, cy + 1.0 * unit, cx + 1.8 * unit, cy + 0.2 * unit))
            p.drawLine(QLineF(cx + 2.6 * unit, cy + 1.0 * unit, cx + 1.8 * unit, cy + 1.8 * unit))
        elif name == "lock":
            p.drawRoundedRect(
                QRectF(cx - 2.1 * unit, cy - 0.2 * unit, 4.2 * unit, 3.1 * unit),
                unit * 0.5,
                unit * 0.5,
            )
            offset = 0 if self._position_locked else -0.7 * unit
            p.drawArc(
                QRectF(cx - 1.45 * unit + offset, cy - 2.8 * unit, 2.9 * unit, 3.2 * unit),
                0,
                180 * 16,
            )
        elif name == "top":
            p.drawLine(QLineF(cx - 2.4 * unit, cy - 2.5 * unit, cx + 2.4 * unit, cy - 2.5 * unit))
            p.drawLine(QLineF(cx, cy + 2.7 * unit, cx, cy - 1.7 * unit))
            p.drawLine(QLineF(cx, cy - 1.7 * unit, cx - 1.25 * unit, cy - 0.4 * unit))
            p.drawLine(QLineF(cx, cy - 1.7 * unit, cx + 1.25 * unit, cy - 0.4 * unit))
        elif name in ("smaller", "larger"):
            p.drawLine(QLineF(cx - 2.0 * unit, cy, cx + 2.0 * unit, cy))
            if name == "larger":
                p.drawLine(QLineF(cx, cy - 2.0 * unit, cx, cy + 2.0 * unit))
        elif name == "keyboard_opacity":
            circle = QRectF(cx - 2.25 * unit, cy - 2.25 * unit, 4.5 * unit, 4.5 * unit)
            p.drawEllipse(circle)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(205, 233, 249, 210))
            p.drawPie(circle, 90 * 16, 180 * 16)
        elif name == "active_opacity":
            circle = QRectF(cx - 2.2 * unit, cy - 2.2 * unit, 4.4 * unit, 4.4 * unit)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for index, pitch in enumerate((0, 4, 7)):
                p.setPen(QPen(self._note_color(pitch + 60, 235), max(1.2, unit * 0.7)))
                p.drawArc(circle, (90 + index * 120) * 16, 105 * 16)

    def _draw_note_labels(
        self,
        p: QPainter,
        now: float,
        white: dict[int, QRectF],
        black: dict[int, QRectF],
    ) -> None:
        # Keep only the newest label for each pitch, then anchor it directly
        # above that key instead of laying labels out as an unrelated sentence.
        newest: dict[int, VisualNote] = {}
        for note in self.visual_notes[-24:]:
            newest[note.midi] = note
        visible = sorted(
            sorted(newest.values(), key=lambda note: note.born, reverse=True)[:16],
            key=lambda note: note.midi,
        )
        if not visible:
            return
        font = QFont("Inter, Arial, sans-serif", max(9, round(self.height() * 0.068)))
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        metrics = QFontMetricsF(font)
        solfege_font = QFont("Inter, Arial, sans-serif", max(7, round(self.height() * 0.047)))
        solfege_metrics = QFontMetricsF(solfege_font)
        lane_right_edges = [-1e9] * 3
        keyboard_top = next(iter(white.values())).top()
        for note in visible:
            key_rect = white.get(note.midi)
            if key_rect is None:
                key_rect = black.get(note.midi)
            if key_rect is None:
                continue
            alpha = self._alpha(note, now)
            age = now - note.born
            solfege = SOLFEGE_NAMES[note.midi % 12]
            note_width = metrics.horizontalAdvance(note.name)
            solfege_width = solfege_metrics.horizontalAdvance(solfege)
            width = max(note_width, solfege_width)
            center_x = key_rect.center().x()
            left = center_x - width / 2
            available_lane = next(
                (
                    index
                    for index, right_edge in enumerate(lane_right_edges)
                    if left > right_edge + 3
                ),
                None,
            )
            if available_lane is None:
                available_lane = min(
                    range(len(lane_right_edges)),
                    key=lane_right_edges.__getitem__,
                )
                left = lane_right_edges[available_lane] + 3
            lane = available_lane
            lane_right_edges[lane] = left + width
            baseline = self.height() * (0.27 + lane * 0.115)
            y = baseline - min(5, age * 3)
            solfege_y = y + solfege_metrics.height() * 0.92

            guide = self._note_color(note.midi, round(70 * alpha))
            p.save()
            p.setOpacity(self._active_opacity)
            p.setPen(QPen(guide, 0.8))
            p.drawLine(
                QLineF(
                    center_x,
                    solfege_y + 2,
                    key_rect.center().x(),
                    keyboard_top - 3,
                )
            )
            p.restore()
            text_alpha = round(185 + 70 * alpha)
            p.save()
            p.setOpacity(self._active_opacity)
            p.setFont(font)
            p.setPen(self._note_color(note.midi, text_alpha))
            p.drawText(QPoint(round(center_x - note_width / 2), round(y)), note.name)
            p.setFont(solfege_font)
            p.setPen(self._note_color(note.midi, text_alpha))
            p.drawText(
                QPoint(round(center_x - solfege_width / 2), round(solfege_y)),
                solfege,
            )
            p.restore()

    def _draw_keyboard(self, p: QPainter, white, black, now: float) -> None:
        active: dict[int, float] = {}
        for note in self.visual_notes:
            active[note.midi] = max(active.get(note.midi, 0), self._alpha(note, now) * note.strength)
        self._draw_active_auras(p, white, black, active)
        ordered_white = sorted(white.values(), key=lambda rect: rect.left())
        white_bed = QRectF(
            ordered_white[0].left(),
            ordered_white[0].top(),
            ordered_white[-1].right() - ordered_white[0].left(),
            ordered_white[0].height(),
        )
        resting_white = QLinearGradient(white_bed.topLeft(), white_bed.bottomLeft())
        resting_white.setColorAt(0, QColor(230, 237, 246, 255))
        resting_white.setColorAt(1, QColor(154, 170, 190, 250))
        p.save()
        p.setOpacity(self._opacity)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(resting_white)
        p.drawRect(white_bed)
        p.restore()
        for midi, rect in white.items():
            glow = active.get(midi, 0)
            if not glow:
                continue
            base = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            color = self._note_color(midi)
            # White keys need a brighter center to offset their larger
            # illuminated area and the pale resting-key substrate.
            light = color.lighter(175)
            center_color = color.lighter(135)
            deep = color.darker(105)
            alpha = round(185 + 70 * glow)
            light.setAlpha(alpha)
            center_color.setAlpha(alpha)
            deep.setAlpha(round(alpha * 0.97))
            base.setColorAt(0, light)
            base.setColorAt(0.42, center_color)
            base.setColorAt(1, deep)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(base)
            p.save()
            p.setOpacity(self._active_key_opacity())
            p.drawRect(rect)
            p.restore()
        p.save()
        p.setOpacity(self._opacity)
        self._draw_white_key_separators(p, white, black)
        p.restore()
        for midi, rect in black.items():
            glow = active.get(midi, 0)
            base = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            base.setColorAt(0, QColor(42, 52, 68, 255))
            base.setColorAt(1, QColor(8, 14, 25, 250))
            if glow:
                color = self._note_color(midi)
                # Keep black keys saturated, but reduce their center luminance
                # so the dark substrate no longer makes them dominate.
                light = color.lighter(110)
                center_color = color.darker(130)
                deep = color.darker(200)
                alpha = round(160 + 70 * glow)
                light.setAlpha(alpha)
                center_color.setAlpha(alpha)
                deep.setAlpha(round(alpha * 0.86))
                base.setColorAt(0, light)
                base.setColorAt(0.48, center_color)
                base.setColorAt(1, deep)
            edge = self._note_color(midi, round(30 + 110 * glow))
            p.setPen(QPen(edge, 0.7))
            p.setBrush(base)
            if glow:
                p.save()
                p.setOpacity(self._active_key_opacity())
                p.drawRoundedRect(rect, 2, 2)
                p.restore()
            else:
                p.save()
                p.setOpacity(self._opacity)
                p.drawRoundedRect(rect, 2, 2)
                p.restore()
        # Draw center glows only after both key layers exist. Previously black
        # keys covered part of every neighboring white-key glow.
        self._draw_active_center_glows(p, white, black, active)
        self._draw_active_key_edges(p, white, black, active)

    def _draw_erhu(self, p: QPainter, now: float) -> None:
        """Draw two pitch-position guides while preserving the overlay controls."""
        labels = {"inner": "内弦 D", "outer": "外弦 A"}
        vertical = self._erhu_vertical
        if vertical:
            top = 88.0
            body_bottom = self.height() - 17.0
            string_axis = self._erhu_vertical_string_axis()
            body_rect = (
                self._erhu_body_rect(
                    vertical=True,
                    bottom=body_bottom,
                    string_axis=string_axis,
                )
                if self._erhu_body
                else None
            )
            bottom = (
                body_rect.top() - 5.0
                if body_rect is not None
                else body_bottom
            )
            usable = max(1.0, bottom - top)

            def point(string_name: str, position: float) -> tuple[float, float]:
                return (
                    string_axis[string_name],
                    bottom - position / MAX_POSITION * usable,
                )
        else:
            left = 96.0
            right = self.width() - 32.0
            usable = max(1.0, right - left)
            string_axis = self._erhu_horizontal_string_axis()

            def point(string_name: str, position: float) -> tuple[float, float]:
                return (
                    left + position / MAX_POSITION * usable,
                    string_axis[string_name],
                )

        if self._erhu_vertical and self._erhu_body:
            self._draw_erhu_body(
                p,
                vertical=vertical,
                left=left if not vertical else None,
                right=right if not vertical else None,
                bottom=body_bottom if vertical else None,
                string_axis=string_axis,
            )

        if vertical and self._erhu_body:
            self._draw_erhu_top_bars(p, top=top, string_axis=string_axis)

        p.save()
        # Structural guides must remain readable over pale wallpapers even
        # when the user lowers the glass/keyboard opacity.
        p.setOpacity(max(0.72, self._opacity))
        p.setFont(QFont("Inter, Noto Sans CJK SC, sans-serif", 8))
        vertical_label_rects = (
            self._erhu_vertical_label_rects(top=top, string_axis=string_axis)
            if vertical
            else {}
        )
        for string_name, axis in string_axis.items():
            selected = (
                self._erhu_state is not None
                and self._erhu_state.string_name == string_name
            )
            if selected:
                string_color = self._erhu_note_color(
                    self._erhu_state.midi, string_name, 235
                )
                shadow_color = QColor(8, 16, 27, 175)
                width = 2.35
            else:
                base_string = QColor(151, 181, 203, 230)
                string_color = (
                    base_string.lighter(118)
                    if string_name == "outer"
                    else base_string.darker(118)
                )
                shadow_color = QColor(7, 13, 23, 195)
                width = 1.45
            if vertical:
                p.setPen(QPen(shadow_color, width + 2.2))
                p.drawLine(QLineF(axis, top, axis, bottom))
                p.setPen(QPen(string_color, width))
                p.drawLine(QLineF(axis, top, axis, bottom))
                label_color = (
                    QColor(224, 238, 248, 225)
                    if string_name == "outer"
                    else QColor(165, 190, 209, 220)
                )
                p.setPen(label_color)
                p.drawText(
                    vertical_label_rects[string_name],
                    Qt.AlignmentFlag.AlignCenter,
                    labels[string_name],
                )
            else:
                p.setPen(QPen(shadow_color, width + 2.2))
                p.drawLine(QLineF(left, axis, right, axis))
                p.setPen(QPen(string_color, width))
                p.drawLine(QLineF(left, axis, right, axis))
                label_color = (
                    QColor(224, 238, 248, 225)
                    if string_name == "outer"
                    else QColor(165, 190, 209, 220)
                )
                p.setPen(label_color)
                p.drawText(
                    QRectF(20, axis - 11, 67, 22),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    labels[string_name],
                )
            for position in range(MAX_POSITION + 1):
                x, y = point(string_name, position)
                length = 5.0 if position % 3 else 8.0
                tick_color = (
                    QColor(220, 239, 250, 145)
                    if string_name == "outer"
                    else QColor(139, 169, 190, 135)
                )
                p.setPen(QPen(tick_color, 0.8))
                if vertical:
                    p.drawLine(QLineF(x - length / 2, y, x + length / 2, y))
                else:
                    p.drawLine(QLineF(x, y - length / 2, x, y + length / 2))
        p.restore()

        if self._erhu_history:
            # The active note is drawn below as the main glowing point. Historical
            # notes are the previous notes only: newest previous note is 50%
            # opacity, then each older note halves again.
            for index, trail in enumerate(reversed(self._erhu_trails[:-1])):
                alpha = self._erhu_history_alpha(index)
                if alpha < 8:
                    continue
                state = trail.state
                x, y = point(state.string_name, state.position)
                p.save()
                p.setOpacity(self._active_opacity)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(self._erhu_note_color(state.midi, state.string_name, alpha))
                diameter = self._erhu_history_diameter(index)
                p.drawEllipse(
                    QRectF(
                        x - diameter / 2,
                        y - diameter / 2,
                        diameter,
                        diameter,
                    )
                )
                p.restore()

        newest_trail = self._erhu_trails[-1] if self._erhu_trails else None
        for trail in self._erhu_trails:
            age = now - trail.born
            if age >= 0.42:
                continue
            state = trail.state
            if trail is newest_trail:
                onset_delay = 0.055
                if age < onset_delay:
                    continue
                x, y = point(state.string_name, self._erhu_display_position)
                progress = max(0.0, (age - onset_delay) / 0.42)
            else:
                x, y = point(state.string_name, state.position)
                progress = max(0.0, age / 0.42)
            radius = 9.0 + progress * 25.0
            ring = self._erhu_note_color(
                state.midi,
                state.string_name,
                round(205 * (1.0 - progress)),
            )
            p.save()
            p.setOpacity(self._active_opacity)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(ring, max(0.7, 2.1 * (1.0 - progress))))
            p.drawEllipse(
                QRectF(
                    x - radius,
                    y - radius,
                    radius * 2,
                    radius * 2,
                )
            )
            p.restore()

        state = self._erhu_state
        if state is None:
            p.setFont(QFont("Inter, Noto Sans CJK SC, sans-serif", 9))
            p.setPen(QColor(185, 205, 222, 135))
            p.drawText(
                QRectF(90, self.height() * 0.39, self.width() - 180, 24),
                Qt.AlignmentFlag.AlignCenter,
                "Erhu Shadow · 等待主旋律",
            )
            return
        x, y = point(state.string_name, self._erhu_display_position)
        color = self._erhu_note_color(state.midi, state.string_name)
        p.save()
        p.setOpacity(self._active_opacity)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        glow = QRadialGradient(QPointF(x, y), 31.0)
        glow.setColorAt(
            0, self._erhu_note_color(state.midi, state.string_name, 210)
        )
        glow.setColorAt(
            0.35, self._erhu_note_color(state.midi, state.string_name, 95)
        )
        glow.setColorAt(
            1, self._erhu_note_color(state.midi, state.string_name, 0)
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QRectF(x - 31, y - 31, 62, 62))
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setBrush(color)
        p.setPen(QPen(color.lighter(145), 1.2))
        p.drawEllipse(QRectF(x - 7.5, y - 7.5, 15, 15))
        p.restore()

        chinese_string = "内弦" if state.string_name == "inner" else "外弦"
        jianpu = ERHU_D_JIANPU[state.midi % 12]
        p.save()
        p.setOpacity(self._active_opacity)
        name_font = QFont("Inter, Noto Sans CJK SC, sans-serif", 13)
        name_font.setWeight(QFont.Weight.DemiBold)
        p.setFont(name_font)
        p.setPen(color)
        if vertical:
            controls = self._control_rects()
            control_left = min(rect.left() for rect in controls.values())
            note_rect = QRectF(18, 124, max(120.0, control_left - 28.0), 26)
            note_align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        else:
            note_rect = QRectF(96, self.height() * 0.39, self.width() - 128, 24)
            note_align = Qt.AlignmentFlag.AlignCenter
        p.drawText(
            note_rect,
            note_align,
            (
                f"{state.note_name}  ·  {chinese_string} {state.position}"
                f"  ·  D调 {jianpu}"
            ),
        )
        p.restore()

    def _active_key_opacity(self) -> float:
        return self._active_opacity

    def _draw_active_center_glows(
        self,
        p: QPainter,
        white: dict[int, QRectF],
        black: dict[int, QRectF],
        active: dict[int, float],
    ) -> None:
        p.save()
        p.setOpacity(self._active_key_opacity())
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        for midi, strength in active.items():
            is_white = midi in white
            rect = white.get(midi)
            if rect is None:
                rect = black.get(midi)
            if rect is None:
                continue
            # A small perceptual compensation offsets the larger illuminated
            # area of white keys without changing pitch colors.
            effective = min(1.0, strength * (1.12 if is_white else 1.0))
            center = rect.center()
            color = self._note_color(midi)
            color = color.lighter(118) if is_white else color.darker(118)
            mid = color.lighter(115)
            radius = max(18, rect.width() * (2.45 if is_white else 3.0))
            glow = QRadialGradient(center, radius)
            mid.setAlpha(round(150 * effective))
            transparent = self._note_color(midi, 0)
            color.setAlpha(round(240 * effective))
            glow.setColorAt(0, color)
            glow.setColorAt(0.38, mid)
            glow.setColorAt(1, transparent)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(center, radius, radius)
        p.restore()

    def _draw_white_key_separators(
        self,
        p: QPainter,
        white: dict[int, QRectF],
        black: dict[int, QRectF],
    ) -> None:
        """Draw a white-key seam only where no black key covers the boundary."""
        ordered = sorted(white.values(), key=lambda rect: rect.left())
        black_centers = [rect.center().x() for rect in black.values()]
        p.save()
        p.setPen(QPen(QColor(10, 19, 31, 95), 0.65))
        for left, right in zip(ordered, ordered[1:]):
            boundary = right.left()
            if any(abs(center - boundary) < 1.0 for center in black_centers):
                continue
            p.drawLine(QLineF(boundary, left.top() + 1, boundary, left.bottom() - 1))
        p.restore()

    def _draw_active_auras(
        self,
        p: QPainter,
        white: dict[int, QRectF],
        black: dict[int, QRectF],
        active: dict[int, float],
    ) -> None:
        if not active:
            return
        keyboard_top = next(iter(white.values())).top()
        p.save()
        p.setOpacity(self._active_key_opacity())
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        p.setPen(Qt.PenStyle.NoPen)
        for midi, strength in active.items():
            rect = white.get(midi)
            if rect is None:
                rect = black.get(midi)
            if rect is None:
                continue
            center_x = rect.center().x()
            beam_rect = QRectF(
                center_x - max(6, rect.width() * 0.8),
                keyboard_top - 31,
                max(12, rect.width() * 1.6),
                rect.height() + 31,
            )
            beam = QLinearGradient(0, beam_rect.top(), 0, beam_rect.bottom())
            beam.setColorAt(0, self._note_color(midi, 0))
            beam.setColorAt(0.42, self._note_color(midi, round(105 * strength)))
            beam.setColorAt(0.72, self._note_color(midi, round(65 * strength)))
            beam.setColorAt(1, self._note_color(midi, 0))
            p.setBrush(beam)
            p.drawRoundedRect(beam_rect, beam_rect.width() / 2, beam_rect.width() / 2)
        p.restore()

    def _draw_active_key_edges(
        self,
        p: QPainter,
        white: dict[int, QRectF],
        black: dict[int, QRectF],
        active: dict[int, float],
    ) -> None:
        p.save()
        p.setOpacity(self._active_key_opacity())
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        for midi, strength in active.items():
            rect = white.get(midi)
            if rect is None:
                rect = black.get(midi)
            if rect is None:
                continue
            color = self._note_color(midi, round(225 * strength))
            p.setPen(QPen(color, 1.25))
            p.setBrush(Qt.BrushStyle.NoBrush)
            if midi in white:
                p.drawLine(QLineF(rect.left() + 1, rect.bottom() - 1, rect.right() - 1, rect.bottom() - 1))
            else:
                p.drawRoundedRect(rect.adjusted(0.7, 0.7, -0.7, -0.7), 2, 2)
            p.setPen(QPen(self._note_color(midi, round(245 * strength)), 1.8))
            p.drawLine(QLineF(rect.left() + 1.5, rect.top() + 1.2, rect.right() - 1.5, rect.top() + 1.2))
        p.restore()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            control = self._control_at(event.position())
            if control:
                if not self._control_enabled(control):
                    event.accept()
                    return
                self._activate_control(control)
                event.accept()
                return
            if not self._position_locked:
                self._begin_move(event)
        elif event.button() == Qt.MouseButton.RightButton:
            self._show_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_offset
            and not self._native_move
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        self._drag_offset = None
        self._native_move = False
        if not self._position_locked:
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    @staticmethod
    def _performance_key_token(event: QKeyEvent) -> str | None:
        key = event.key()
        function_keys = {
            int(Qt.Key.Key_F1) + index: f"F{index + 1}"
            for index in range(12)
        }
        if key in function_keys:
            return function_keys[key]
        # Ctrl+letter produces a control character in event.text() on Windows.
        # Map physical Qt key codes so Shift/Ctrl accidentals behave identically.
        if ord("0") <= key <= ord("9") or ord("A") <= key <= ord("Z"):
            token = chr(key)
            if token in "1234567890QWERTYUIOPASDFGHJKLZXCVBNM":
                return token
        punctuation_keys = {
            Qt.Key.Key_Minus: "-",
            Qt.Key.Key_Equal: "=",
            Qt.Key.Key_BracketLeft: "[",
            Qt.Key.Key_BracketRight: "]",
            Qt.Key.Key_Semicolon: ";",
            Qt.Key.Key_Apostrophe: "'",
            Qt.Key.Key_Comma: ",",
            Qt.Key.Key_Period: ".",
            Qt.Key.Key_Slash: "/",
        }
        if key in punctuation_keys:
            return punctuation_keys[key]
        return None

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._performance_mode or self._performance is None:
            super().keyPressEvent(event)
            return
        if event.isAutoRepeat():
            event.accept()
            return
        controller = self._performance
        if controller.input_mode != "keyboard":
            event.accept()
            return
        key = event.key()
        if key == Qt.Key.Key_Alt:
            if controller.technique_profile == "piano":
                controller.set_soft(True)
            elif controller.technique_profile == "organ":
                controller.set_organ_modulation(True)
        elif key == Qt.Key.Key_Space:
            alt = bool(
                event.modifiers() & Qt.KeyboardModifier.AltModifier
            )
            if controller.technique_profile == "piano" and alt:
                controller.set_soft(False)
                controller.set_sostenuto(True)
                self._space_sostenuto = True
            elif controller.supports_vibrato:
                self._start_vibrato()
            elif controller.technique_profile == "organ":
                pass
            else:
                controller.set_sustain(True)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            controller.set_rest(True)
        elif key == Qt.Key.Key_Down:
            controller.shift_octave(1)
        elif key == Qt.Key.Key_Up:
            controller.shift_octave(-1)
        elif key == Qt.Key.Key_Right:
            controller.shift_scale(1)
            if controller.ear_training.note_count:
                self._start_ear_question()
        elif key == Qt.Key.Key_Left:
            controller.shift_scale(-1)
            if controller.ear_training.note_count:
                self._start_ear_question()
        else:
            token = self._performance_key_token(event)
            if token:
                modifiers = event.modifiers()
                shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
                control = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
                accidental = 0 if shift and control else 1 if shift else -1 if control else 0
                alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
                glide = (
                    controller.begin_glide(token, accidental)
                    if alt and controller.supports_glide
                    else None
                )
                if glide is not None:
                    self._start_glide(*glide)
                else:
                    controller.press(token, accidental)
        self.update()
        event.accept()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if not self._performance_mode or self._performance is None:
            super().keyReleaseEvent(event)
            return
        if event.isAutoRepeat():
            event.accept()
            return
        if self._performance.input_mode != "keyboard":
            event.accept()
            return
        if event.key() == Qt.Key.Key_Alt:
            if self._performance.technique_profile == "piano":
                self._performance.set_soft(False)
            elif self._performance.technique_profile == "organ":
                self._performance.set_organ_modulation(False)
        elif event.key() == Qt.Key.Key_Space:
            if self._space_sostenuto:
                self._performance.set_sostenuto(False)
                self._space_sostenuto = False
            elif self._performance.supports_vibrato:
                self._stop_vibrato()
            elif self._performance.technique_profile == "organ":
                pass
            else:
                self._performance.set_sustain(False)
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._performance.set_rest(False)
        else:
            token = self._performance_key_token(event)
            if token:
                self._performance.release(token)
        self.update()
        event.accept()

    def _start_vibrato(self) -> None:
        if self._performance is None or not self._performance.supports_vibrato:
            return
        self._vibrato_phase = 0.0
        self._vibrato_timer.start()

    def _vibrato_tick(self) -> None:
        if self._performance is None or not self._performance.supports_vibrato:
            self._stop_vibrato()
            return
        self._vibrato_phase += 1.1
        bend = 8192 + round(math.sin(self._vibrato_phase) * 180)
        self._performance.set_pitch_bend(bend)

    def _stop_vibrato(self) -> None:
        self._vibrato_timer.stop()
        if self._performance is not None:
            self._performance.set_pitch_bend(8192)

    def _start_glide(self, source: int, target: int) -> None:
        if self._performance is None:
            return
        self._stop_vibrato()
        self._glide_generation += 1
        generation = self._glide_generation
        steps = 14
        interval = target - source
        for step in range(1, steps + 1):
            QTimer.singleShot(
                round(step * 420 / steps),
                lambda current=step, token=generation: self._glide_step(
                    token, source, target, interval, current, steps
                ),
            )

    def _glide_step(
        self,
        generation: int,
        source: int,
        target: int,
        interval: int,
        step: int,
        steps: int,
    ) -> None:
        if generation != self._glide_generation or self._performance is None:
            return
        if step < steps:
            bend = 8192 + round((interval / 12) * 8191 * step / steps)
            self._performance.set_pitch_bend(bend)
        else:
            self._performance.finish_glide(source, target)
        self.update()

    @pyqtSlot(int, int)
    def _show_performance_note(self, midi: int, velocity: int) -> None:
        event = NoteEvent(
            midi=midi,
            start=0.0,
            end=0.8,
            velocity=velocity,
            confidence=1.0,
        )
        self._display_notes([event])

    def _cycle_ear_training(self) -> None:
        if self._performance is None:
            return
        self._ear_playback_generation += 1
        self._performance.all_notes_off()
        self._clear_ear_feedback()
        level = self._performance.ear_training.cycle_level()
        self._performance_help = False
        if level == 0:
            self.set_status("听音练习已关闭", False)
        else:
            self.set_status(f"听音练习 · {level} 音", False)
            generation = self._ear_playback_generation
            QTimer.singleShot(
                250,
                lambda token=generation: self._start_ear_question_if_current(token),
            )
        self.update()

    def _start_ear_question_if_current(self, generation: int) -> None:
        if generation == self._ear_playback_generation:
            self._start_ear_question()

    def _start_ear_question(self) -> None:
        if self._performance is None:
            return
        session = self._performance.ear_training
        if session.note_count == 0:
            return
        target = session.new_question(
            session.rng.choice(("major", "minor")),
            self._performance.scale_index,
        )
        self._play_ear_target(target)

    def _play_ear_target(self, target: tuple[int, ...] | None = None) -> None:
        if self._performance is None:
            return
        session = self._performance.ear_training
        target = target or session.replay()
        if not target or session.note_count == 0:
            return
        self._ear_playback_generation += 1
        self._clear_ear_feedback()
        generation = self._ear_playback_generation
        self._performance.all_notes_off()
        self.set_status(f"听音练习 · {session.note_count} 音 · 请听", False)
        interval_ms = 360
        duration_ms = 230
        for index, midi in enumerate(target):
            QTimer.singleShot(
                index * interval_ms,
                lambda note=midi, token=generation: self._play_ear_note(token, note),
            )
            QTimer.singleShot(
                index * interval_ms + duration_ms,
                lambda note=midi, token=generation: self._stop_ear_note(token, note),
            )
        QTimer.singleShot(
            len(target) * interval_ms + 80,
            lambda token=generation: self._begin_ear_answer(token),
        )

    def _play_ear_note(self, generation: int, midi: int) -> None:
        if generation != self._ear_playback_generation or self._performance is None:
            return
        self._performance.synth.note_on(midi, 92)

    def _stop_ear_note(self, generation: int, midi: int) -> None:
        if generation == self._ear_playback_generation and self._performance is not None:
            self._performance.synth.note_off(midi)

    def _begin_ear_answer(self, generation: int) -> None:
        if generation != self._ear_playback_generation or self._performance is None:
            return
        session = self._performance.ear_training
        if session.note_count == 0:
            return
        session.accepting = True
        self.set_status(
            f"听音练习 · {session.note_count} 音 · 请按顺序复现",
            False,
        )
        QTimer.singleShot(
            2000,
            lambda token=generation: self._replay_ear_question_if_current(token),
        )

    @pyqtSlot(int)
    def _handle_ear_answer(self, midi: int) -> None:
        if self._performance is None:
            return
        session = self._performance.ear_training
        result = session.submit(midi)
        if result != "ignored":
            # A real answer attempt owns the interaction now. Invalidate the
            # pending two-second demonstration replay so it cannot interrupt
            # a multi-note response.
            self._ear_playback_generation += 1
        if result == "continue":
            self.set_status(
                f"听音练习 · 已答对 {len(session.answer)}/{session.note_count}",
                False,
            )
        elif result == "correct":
            self._ear_feedback_target = session.target
            self._ear_feedback_error = None
            self._ear_feedback_correct = True
            self.set_status("听音练习 · 正确，下一组", False)
            self.update()
            generation = self._ear_playback_generation
            QTimer.singleShot(
                1400,
                lambda token=generation: self._start_ear_question_if_current(token),
            )
        elif result == "wrong":
            self._ear_feedback_target = session.target
            self._ear_feedback_error = session.last_error
            self._ear_feedback_correct = False
            self.set_status("听音练习 · 不对，再听一次", True)
            self.update()
            generation = self._ear_playback_generation
            QTimer.singleShot(
                2000,
                lambda token=generation: self._replay_ear_question_if_current(token),
            )

    def _replay_ear_question_if_current(self, generation: int) -> None:
        if generation != self._ear_playback_generation or self._performance is None:
            return
        self._play_ear_target(self._performance.ear_training.replay())

    def _clear_ear_feedback(self) -> None:
        self._ear_feedback_target = ()
        self._ear_feedback_error = None
        self._ear_feedback_correct = False
        self.update()

    def _toggle_performance_mode(self, enabled: bool) -> None:
        if enabled == self._performance_mode:
            return
        self._performance_mode = enabled
        self._performance_help = False
        self._glide_generation += 1
        self._stop_vibrato()
        self._space_sostenuto = False
        self._ear_playback_generation += 1
        self._clear_ear_feedback()
        self.visual_notes.clear()
        if enabled:
            self._toggle_position_lock(False)
            self._performance = PerformanceController(
                self.performance_note_received.emit,
                self.performance_answer_received.emit,
                sound_source=self._sound_source,
                instrument_index=self._instrument_index,
                soundfont_path=SOUNDFONT_PATH,
            )
            self._sound_source = self._performance.sound_source
            self._performance.reset()
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.activateWindow()
            self.raise_()
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.set_status("演奏模式", False)
        else:
            if self._performance is not None:
                self._performance.close()
                self._performance = None
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.set_status("Piano Shadow · Listening", False)
        self.performance_mode_changed.emit(enabled)
        self.update()

    def _control_at(self, point) -> str | None:
        for name, rect in self._control_rects().items():
            if rect.contains(point):
                return name
        return None

    def _locked_hit_is_interactive(self, point: QPoint) -> bool:
        """Keep only the lock control clickable while the overlay is locked."""
        lock_rect = self._control_rects().get("lock")
        return bool(
            lock_rect
            and lock_rect.adjusted(-4, -4, 4, 4).contains(point.x(), point.y())
        )

    def nativeEvent(self, event_type, message):
        """On Windows, pass locked-window clicks through except on the lock icon."""
        if platform.system() == "Windows" and self._click_through:
            try:
                import ctypes
                from ctypes import wintypes

                msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
                if msg.message == 0x0084:  # WM_NCHITTEST
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    local = self.mapFromGlobal(QPoint(x, y))
                    if not self._locked_hit_is_interactive(local):
                        return True, -1  # HTTRANSPARENT
            except Exception:
                pass
        return False, 0

    def _begin_move(self, event: QMouseEvent) -> None:
        self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        handle = self.windowHandle()
        self._native_move = bool(handle and handle.startSystemMove())
        event.accept()

    def _activate_control(self, name: str) -> None:
        if name == "performance":
            if self._visual_mode != "piano":
                self.set_status("演奏模式仅在钢琴模式中提供", False)
                self.update()
                return
            self._toggle_performance_mode(not self._performance_mode)
        elif name == "visual_mode":
            self._set_visual_mode(
                "piano" if self._visual_mode == "erhu" else "erhu"
            )
        elif name == "performance_help":
            self._performance_help = not self._performance_help
        elif name == "ear_training":
            self._cycle_ear_training()
        elif name == "input_mode" and self._performance is not None:
            self._performance.toggle_input_mode()
        elif name == "instrument_prev":
            self._shift_instrument(-1)
        elif name == "instrument_next":
            self._shift_instrument(1)
        elif name == "instrument_label":
            self._toggle_sound_source()
        elif name == "instrument_reset":
            self._reset_performance_sound()
        elif name == "soundfont_manage":
            self._show_soundfont_manager()
        elif name == "minimal":
            self._toggle_keyboard_only(True)
        elif name == "piano_model":
            next_model = (
                "basic-pitch"
                if self.config.model == "piano-gpu"
                else "piano-gpu"
            )
            self._select_model(next_model)
        elif name == "erhu_rotate":
            self._set_erhu_orientation(not self._erhu_vertical)
        elif name == "erhu_history":
            self._erhu_history = not self._erhu_history
            if not self._erhu_history:
                self._erhu_trails.clear()
            state = "开启" if self._erhu_history else "关闭"
            self.set_status(f"二胡历史轨迹 · {state}", False)
        elif name == "erhu_body":
            if not self._erhu_vertical:
                self.set_status("横向二胡不显示琴托", False)
                return
            self._erhu_body = not self._erhu_body
            state = "显示" if self._erhu_body else "隐藏"
            self.set_status(f"二胡结构件 · {state}", False)
        elif name == "erhu_mirror":
            self._erhu_mirrored = not self._erhu_mirrored
            state = "镜像" if self._erhu_mirrored else "默认"
            self.set_status(f"二胡视角 · {state}", False)
        elif name == "lock":
            if self._keyboard_only:
                self._toggle_keyboard_only(False)
            else:
                self._toggle_position_lock(not self._position_locked)
        elif name == "top":
            # Windows can toggle native topmost without rebuilding the window.
            # Other compositors keep the idempotent behavior to avoid jumps.
            enabled = not self._always_on_top if platform.system() == "Windows" else True
            self._toggle_topmost(enabled)
            qt_platform = QApplication.platformName().lower()
            if "wayland" in qt_platform:
                self.set_status(
                    "置顶已请求 · Wayland 是否执行取决于桌面合成器", True
                )
        elif name == "smaller":
            self._set_scale(self._scale_percent - 10)
        elif name == "larger":
            self._set_scale(self._scale_percent + 10)
        elif name == "keyboard_opacity":
            levels = (0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
            current = round(self._opacity * 100)
            next_level = next(
                (level for level in levels if level > current), 0
            )
            self._opacity = next_level / 100
            self.set_status(f"键盘透明度 {next_level}%", False)
        elif name == "active_opacity":
            levels = (30, 40, 50, 60, 70, 80, 90, 100)
            current = round(self._active_opacity * 100)
            next_level = next(
                (level for level in levels if level > current), 30
            )
            self._active_opacity = next_level / 100
            self.set_status(f"彩色高亮透明度 {next_level}%", False)
        self.update()

    def _shift_instrument(self, amount: int) -> None:
        if self._performance is None:
            return
        self._glide_generation += 1
        self._stop_vibrato()
        self._space_sostenuto = False
        self._performance.shift_instrument(amount)
        self._instrument_index = self._performance.instrument_index
        self.set_status(
            f"音色 · {self._performance.sound_label}",
            False,
        )
        self.update()

    def _toggle_sound_source(self) -> None:
        if self._performance is None:
            return
        if self._performance.sound_source == "soundfont":
            if self._performance.use_windows():
                self._sound_source = "windows"
                self.set_status(
                    f"音源 · {self._performance.sound_label}",
                    False,
                )
            else:
                self.set_status("Windows MIDI 音源不可用", True)
            self.update()
            return
        if not self._soundfont_is_installed():
            self._show_soundfont_manager()
            return
        if self._performance.use_soundfont(SOUNDFONT_PATH):
            self._sound_source = "soundfont"
            self.set_status(
                f"音源 · {self._performance.sound_label}",
                False,
            )
        else:
            self._sound_source = "windows"
            self.set_status(
                "SoundFont 播放引擎不可用 · 已保持 Windows 音源",
                True,
            )
        self.update()

    def _reset_performance_sound(self) -> None:
        if self._performance is None:
            return
        self._glide_generation += 1
        self._stop_vibrato()
        self._space_sostenuto = False
        self._performance.instrument_index = 0
        if not self._performance.use_windows():
            self.set_status("Windows MIDI 音源不可用", True)
            return
        self._performance.synth.set_program(0)
        self._instrument_index = 0
        self._sound_source = "windows"
        self.set_status("已恢复默认 · WIN · 大钢琴", False)
        self.update()

    def _show_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        top = QAction("始终置顶", self, checkable=True, checked=self._always_on_top)
        top.triggered.connect(self._toggle_topmost)
        locked = QAction("锁定位置", self, checkable=True, checked=self._position_locked)
        locked.triggered.connect(self._toggle_position_lock)
        minimal = QAction("纯键盘模式", self, checkable=True, checked=self._keyboard_only)
        minimal.triggered.connect(self._toggle_keyboard_only)
        performance = QAction(
            "演奏模式", self, checkable=True, checked=self._performance_mode
        )
        performance.triggered.connect(self._toggle_performance_mode)
        soundfont = QAction("音源与 SoundFont…", self)
        soundfont.triggered.connect(self._show_soundfont_manager)
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(top)
        menu.addAction(locked)
        menu.addAction(minimal)
        menu.addAction(performance)
        menu.addAction(soundfont)
        menu.addSeparator()
        visual_menu = menu.addMenu("可视化模式")
        visual_group = QActionGroup(visual_menu)
        visual_group.setExclusive(True)
        for title, mode in (
            ("钢琴模式", "piano"),
            ("二胡模式 · Erhu Shadow", "erhu"),
        ):
            action = QAction(
                title,
                visual_menu,
                checkable=True,
                checked=self._visual_mode == mode,
            )
            action.triggered.connect(
                lambda checked, selected=mode: checked
                and self._set_visual_mode(selected)
            )
            visual_group.addAction(action)
            visual_menu.addAction(action)
        model_menu = menu.addMenu("识别模型")
        model_menu.setEnabled(self._visual_mode == "piano")
        if self._visual_mode == "erhu":
            model_menu.setTitle("识别模型 · 二胡固定 Basic Pitch")
        model_group = QActionGroup(model_menu)
        model_group.setExclusive(True)
        for title, model_name in (
            ("Basic Pitch · 快速通用", "basic-pitch"),
            ("Piano GPU · 推荐 · 钢琴高精度", "piano-gpu"),
        ):
            action = QAction(
                title,
                model_menu,
                checkable=True,
                checked=self.config.model == model_name,
            )
            action.triggered.connect(
                lambda checked, name=model_name: checked and self._select_model(name)
            )
            model_group.addAction(action)
            model_menu.addAction(action)
        menu.addSeparator()
        menu.addAction(self._keyboard_opacity_action(menu))
        menu.addAction(self._active_opacity_action(menu))
        menu.addAction(self._size_action(menu))
        menu.addSeparator()
        menu.addAction(quit_action)
        menu.exec(position)

    def _set_visual_mode(self, mode: str) -> None:
        if mode not in {"piano", "erhu"} or mode == self._visual_mode:
            return
        if mode == "piano" and self._erhu_vertical:
            self._set_erhu_orientation(False)
        self._visual_mode = mode
        self.visual_notes.clear()
        self._erhu_trails.clear()
        self._erhu_state = None
        self._erhu_display_position = 0.0
        self._erhu_target_position = 0.0
        self._erhu_mapper.reset()
        label = "钢琴模式" if mode == "piano" else "二胡模式 · Erhu Shadow"
        target_model = "piano-gpu" if mode == "piano" else "basic-pitch"
        model_label = "Piano GPU" if mode == "piano" else "Basic Pitch 主旋律"
        was_performance = self._performance_mode
        if mode == "erhu" and was_performance:
            # Set the desired listener before leaving performance mode so the
            # resume signal cannot briefly restart the piano model.
            self.config.model = target_model
            self._toggle_performance_mode(False)
        self.set_status(f"{label} · 正在加载 {model_label}", False)
        if self.config.model != target_model:
            self.config.model = target_model
            self.model_selected.emit(target_model)
        elif not was_performance:
            # The visual mode owns its model. Reasserting it also lets the
            # controller recover if a previous worker stopped unexpectedly.
            self.model_selected.emit(target_model)
        self.visual_mode_changed.emit(mode)
        self.update()

    def _set_erhu_orientation(self, vertical: bool) -> None:
        if vertical == self._erhu_vertical:
            return
        center = self.frameGeometry().center()
        old_size = self.size()
        self._erhu_vertical = vertical
        if vertical:
            self._erhu_body = True
            self._erhu_mirrored = False
        self.setFixedSize(QSize(old_size.height(), old_size.width()))
        self.move(
            center.x() - self.width() // 2,
            center.y() - self.height() // 2,
        )
        orientation = "竖向" if vertical else "横向"
        self.set_status(f"二胡弦 · {orientation}", False)
        self.update()

    def _select_model(self, model_name: str) -> None:
        if self._visual_mode == "erhu" and model_name != "basic-pitch":
            self.set_status(
                "二胡模式固定使用 Basic Pitch 主旋律模型", False
            )
            return
        if model_name == self.config.model:
            return
        if model_name == "piano-gpu":
            if not self._confirm_gpu_requirements():
                self.update()
                return
            if (
                not PIANO_MODEL_PATH.exists()
                or PIANO_MODEL_PATH.stat().st_size < PIANO_MODEL_MIN_BYTES
            ):
                from config import PIANO_MODEL_URL

                self.model_download_required.emit(
                    str(PIANO_MODEL_PATH), PIANO_MODEL_URL
                )
                self.update()
                return
        self.config.model = model_name
        self.model_selected.emit(model_name)
        self.update()

    @pyqtSlot(str)
    def _handle_model_fallback(self, model_name: str) -> None:
        if self.config.model != model_name:
            self._select_model(model_name)

    @pyqtSlot(str, str)
    def _show_model_download_dialog(self, destination: str, url: str) -> None:
        if not self._confirm_gpu_requirements():
            return
        if self._model_download_prompt_shown:
            return
        self._model_download_prompt_shown = True
        box = QMessageBox(self)
        box.setWindowTitle("Piano GPU 模型未安装")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(
            "Piano GPU 需要单独下载约 165MB 的模型权重。<br><br>"
            "程序可以自动下载、校验并安装到：<br>"
            f"<code>{destination}</code>"
        )
        install = box.addButton("自动下载并安装", QMessageBox.ButtonRole.AcceptRole)
        local = box.addButton("选择本地模型文件", QMessageBox.ButtonRole.ActionRole)
        browser = box.addButton("浏览器手动下载", QMessageBox.ButtonRole.ActionRole)
        box.addButton("继续使用 Basic Pitch", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() is install:
            self._download_model(destination, url)
        elif box.clickedButton() is local:
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "选择 Piano GPU 模型",
                str(Path.home()),
                "PyTorch 模型 (*.pth);;所有文件 (*)",
            )
            if selected:
                self._download_model(destination, Path(selected).as_uri())
            else:
                self._model_download_prompt_shown = False
        elif box.clickedButton() is browser:
            QDesktopServices.openUrl(QUrl(url))
            self._model_download_prompt_shown = False
        else:
            self._model_download_prompt_shown = False

    def _confirm_gpu_requirements(self) -> bool:
        if self._gpu_requirements_confirmed:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("启用 Piano GPU 前请确认")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(
            "<b>Piano GPU 仅支持 NVIDIA 显卡。</b><br><br>"
            "继续前请确认电脑具备：<br>"
            "• NVIDIA 独立显卡与可用驱动<br>"
            "• CUDA 版 PyTorch 运行环境<br>"
            "• 约 164MB 的 Piano GPU 模型<br><br>"
            "不满足条件时程序会自动回退到 Basic Pitch CPU。"
        )
        proceed = box.addButton("我已确认，继续", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        confirmed = box.clickedButton() is proceed
        if confirmed:
            self._gpu_requirements_confirmed = True
        return confirmed

    def _download_model(self, destination: str, url: str) -> None:
        if self._model_download_thread and self._model_download_thread.is_alive():
            return
        target = Path(destination)
        partial = target.with_suffix(target.suffix + ".part")
        progress = QProgressDialog("正在下载 Piano GPU 模型…", "取消", 0, 100, self)
        progress.setWindowTitle("Piano Shadow 模型安装")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        self._model_download_progress = progress
        self._model_download_cancel.clear()
        progress.canceled.connect(self._model_download_cancel.set)
        from config import PIANO_MODEL_URLS

        sources = (
            tuple(dict.fromkeys((url, *PIANO_MODEL_URLS)))
            if url in PIANO_MODEL_URLS
            else (url,)
        )
        self._model_download_thread = threading.Thread(
            target=self._download_model_worker,
            args=(target, partial, sources),
            name="model-download",
            daemon=True,
        )
        self._model_download_thread.start()

    def _download_model_worker(
        self, target: Path, partial: Path, sources: tuple[str, ...]
    ) -> None:
        from config import PIANO_MODEL_MIN_BYTES, PIANO_MODEL_SHA256

        errors: list[str] = []
        target.parent.mkdir(parents=True, exist_ok=True)
        for url in sources:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
            host = urllib.parse.urlparse(url).netloc or "本地文件"
            self.model_download_source_received.emit(host)
            try:
                request = urllib.request.Request(
                    url, headers={"User-Agent": "PianoShadow/0.6.0"}
                )
                with urllib.request.urlopen(request, timeout=120) as response:
                    total = int(response.headers.get("Content-Length", "0"))
                    received = 0
                    with partial.open("wb") as output:
                        while not self._model_download_cancel.is_set():
                            block = response.read(1024 * 1024)
                            if not block:
                                break
                            output.write(block)
                            received += len(block)
                            self.model_download_progress_received.emit(
                                received, total
                            )
                if self._model_download_cancel.is_set():
                    raise RuntimeError("下载已取消")
                if (
                    not partial.exists()
                    or partial.stat().st_size < PIANO_MODEL_MIN_BYTES
                ):
                    actual = partial.stat().st_size if partial.exists() else 0
                    raise RuntimeError(
                        f"文件不完整（收到 {actual / 1048576:.1f} MB）"
                    )
                digest = hashlib.sha256()
                with partial.open("rb") as downloaded:
                    for block in iter(
                        lambda: downloaded.read(4 * 1024 * 1024), b""
                    ):
                        digest.update(block)
                if digest.hexdigest() != PIANO_MODEL_SHA256:
                    raise RuntimeError("模型文件 SHA-256 校验失败")
                os.replace(partial, target)
                self.model_download_finished_received.emit(True, str(target))
                return
            except Exception as exc:
                errors.append(f"{host}: {exc}")
                if self._model_download_cancel.is_set():
                    break
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass
        self.model_download_finished_received.emit(False, "\n".join(errors))

    def _update_model_download_progress(self, received: int, total: int) -> None:
        if self._model_download_progress is None:
            return
        if total > 0:
            self._model_download_progress.setValue(
                min(100, round(received * 100 / total))
            )
            self._model_download_progress.setLabelText(
                f"正在下载 Piano GPU 模型… "
                f"{received / 1048576:.1f} / {total / 1048576:.1f} MB"
            )
        else:
            self._model_download_progress.setLabelText(
                f"正在下载 Piano GPU 模型… {received / 1048576:.1f} MB"
            )

    @pyqtSlot(str)
    def _update_model_download_source(self, source: str) -> None:
        if self._model_download_progress is not None:
            self._model_download_progress.setWindowTitle(
                f"Piano Shadow 模型安装 · {source}"
            )

    @pyqtSlot(bool, str)
    def _finish_model_download(self, success: bool, message: str) -> None:
        progress = self._model_download_progress
        self._model_download_progress = None
        self._model_download_thread = None
        if progress is not None:
            progress.close()
            progress.deleteLater()
        if not success:
            QMessageBox.warning(
                self,
                "模型下载未完成",
                f"{message}\n\n可以稍后从托盘菜单重新下载。",
            )
            return
        QMessageBox.information(self, "模型安装完成", "Piano GPU 模型已安装。")
        self._model_download_prompt_shown = False
        self._gpu_requirements_confirmed = True
        if self.config.model != "piano-gpu":
            self._select_model("piano-gpu")

    @staticmethod
    def _soundfont_is_installed() -> bool:
        return (
            SOUNDFONT_PATH.exists()
            and SOUNDFONT_PATH.stat().st_size >= SOUNDFONT_MIN_BYTES
        )

    def _show_soundfont_manager(self) -> None:
        installed = self._soundfont_is_installed()
        box = QMessageBox(self)
        box.setWindowTitle("Piano Shadow 音源")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(
            (
                "GeneralUser GS 已安装。可在 Windows MIDI 与高品质 "
                "SoundFont 之间切换。"
                if installed
                else
                "可选下载 GeneralUser GS（约 31 MB），提供完整 GM 音色。"
            )
            + "<br><br>安装位置：<br>"
            f"<code>{SOUNDFONT_PATH}</code><br><br>"
            "音源由 S. Christian Collins 制作，允许随应用免费分发；"
            "播放引擎 TinySoundFont 使用 MIT 许可证。"
        )
        use = None
        if installed and self._performance is not None:
            target = (
                "Windows 默认音源"
                if self._performance.sound_source == "soundfont"
                else "GeneralUser GS"
            )
            use = box.addButton(
                f"切换到 {target}",
                QMessageBox.ButtonRole.AcceptRole,
            )
        download = box.addButton(
            "重新下载并校验" if installed else "下载并安装",
            QMessageBox.ButtonRole.ActionRole,
        )
        remove = (
            box.addButton("删除 SoundFont", QMessageBox.ButtonRole.DestructiveRole)
            if installed
            else None
        )
        box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if use is not None and clicked is use:
            self._toggle_sound_source()
        elif clicked is download:
            self._download_soundfont()
        elif remove is not None and clicked is remove:
            if (
                self._performance is not None
                and self._performance.sound_source == "soundfont"
            ):
                self._performance.use_windows()
            self._sound_source = "windows"
            try:
                SOUNDFONT_PATH.unlink(missing_ok=True)
                self.set_status("GeneralUser GS 已删除 · 使用 Windows 音源", False)
            except OSError as exc:
                QMessageBox.warning(self, "删除失败", str(exc))
            self.update()

    def _download_soundfont(self) -> None:
        if (
            self._soundfont_download_thread
            and self._soundfont_download_thread.is_alive()
        ):
            return
        partial = SOUNDFONT_PATH.with_suffix(".sf2.part")
        progress = QProgressDialog(
            "正在下载 GeneralUser GS…", "取消", 0, 100, self
        )
        progress.setWindowTitle("Piano Shadow 音源安装")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        self._soundfont_download_progress = progress
        self._soundfont_download_cancel.clear()
        progress.canceled.connect(self._soundfont_download_cancel.set)
        self._soundfont_download_thread = threading.Thread(
            target=self._download_soundfont_worker,
            args=(SOUNDFONT_PATH, partial, SOUNDFONT_URLS),
            name="soundfont-download",
            daemon=True,
        )
        self._soundfont_download_thread.start()

    def _download_soundfont_worker(
        self, target: Path, partial: Path, sources: tuple[str, ...]
    ) -> None:
        errors: list[str] = []
        target.parent.mkdir(parents=True, exist_ok=True)
        for url in sources:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
            host = urllib.parse.urlparse(url).netloc or "本地文件"
            try:
                request = urllib.request.Request(
                    url, headers={"User-Agent": "PianoShadow/0.6.0"}
                )
                with urllib.request.urlopen(request, timeout=120) as response:
                    total = int(response.headers.get("Content-Length", "0"))
                    received = 0
                    with partial.open("wb") as output:
                        while not self._soundfont_download_cancel.is_set():
                            block = response.read(1024 * 1024)
                            if not block:
                                break
                            output.write(block)
                            received += len(block)
                            self.soundfont_download_progress_received.emit(
                                received, total
                            )
                if self._soundfont_download_cancel.is_set():
                    raise RuntimeError("下载已取消")
                if (
                    not partial.exists()
                    or partial.stat().st_size < SOUNDFONT_MIN_BYTES
                ):
                    actual = partial.stat().st_size if partial.exists() else 0
                    raise RuntimeError(
                        f"文件不完整（收到 {actual / 1048576:.1f} MB）"
                    )
                digest = hashlib.sha256()
                with partial.open("rb") as downloaded:
                    for block in iter(
                        lambda: downloaded.read(4 * 1024 * 1024), b""
                    ):
                        digest.update(block)
                if digest.hexdigest() != SOUNDFONT_SHA256:
                    raise RuntimeError("SoundFont SHA-256 校验失败")
                os.replace(partial, target)
                self.soundfont_download_finished_received.emit(
                    True, str(target)
                )
                return
            except Exception as exc:
                errors.append(f"{host}: {exc}")
                if self._soundfont_download_cancel.is_set():
                    break
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass
        self.soundfont_download_finished_received.emit(
            False, "\n".join(errors)
        )

    @pyqtSlot(int, int)
    def _update_soundfont_download_progress(
        self, received: int, total: int
    ) -> None:
        progress = self._soundfont_download_progress
        if progress is None:
            return
        if total > 0:
            progress.setValue(min(100, round(received * 100 / total)))
            progress.setLabelText(
                "正在下载 GeneralUser GS… "
                f"{received / 1048576:.1f} / {total / 1048576:.1f} MB"
            )
        else:
            progress.setLabelText(
                f"正在下载 GeneralUser GS… {received / 1048576:.1f} MB"
            )

    @pyqtSlot(bool, str)
    def _finish_soundfont_download(
        self, success: bool, message: str
    ) -> None:
        progress = self._soundfont_download_progress
        self._soundfont_download_progress = None
        self._soundfont_download_thread = None
        if progress is not None:
            progress.close()
            progress.deleteLater()
        if not success:
            QMessageBox.warning(
                self,
                "音源下载未完成",
                f"{message}\n\n当前仍使用 Windows 默认音源。",
            )
            return
        switched = (
            self._performance is not None
            and self._performance.use_soundfont(SOUNDFONT_PATH)
        )
        if switched:
            self._sound_source = "soundfont"
        QMessageBox.information(
            self,
            "音源安装完成",
            "GeneralUser GS 已安装。"
            + (" 已切换到高品质音源。" if switched else ""),
        )
        self.set_status(
            (
                f"音源 · {self._performance.sound_label}"
                if switched and self._performance is not None
                else "GeneralUser GS 已安装"
            ),
            False,
        )
        self.update()

    def _keyboard_opacity_action(self, menu: QMenu) -> QWidgetAction:
        action = QWidgetAction(menu)
        row = QWidget(menu)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 5, 12, 7)
        label = QLabel("键盘透明度", row)
        value = QLabel(f"{round(self._opacity * 100)}%", row)
        value.setMinimumWidth(34)
        slider = QSlider(Qt.Orientation.Horizontal, row)
        slider.setRange(0, 100)
        slider.setValue(round(self._opacity * 100))
        slider.setMinimumWidth(145)
        slider.setToolTip("调节毛玻璃、黑白底键和普通界面的可见度")

        def change(percent: int) -> None:
            self._opacity = percent / 100
            value.setText(f"{percent}%")
            self.update()

        slider.valueChanged.connect(change)
        layout.addWidget(label)
        layout.addWidget(slider, 1)
        layout.addWidget(value)
        action.setDefaultWidget(row)
        return action

    def _active_opacity_action(self, menu: QMenu) -> QWidgetAction:
        action = QWidgetAction(menu)
        row = QWidget(menu)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 5, 12, 7)
        label = QLabel("彩色高亮", row)
        value = QLabel(f"{round(self._active_opacity * 100)}%", row)
        value.setMinimumWidth(34)
        slider = QSlider(Qt.Orientation.Horizontal, row)
        slider.setRange(30, 100)
        slider.setValue(round(self._active_opacity * 100))
        slider.setMinimumWidth(145)
        slider.setToolTip("调节彩色琴键、光晕、音名与唱名的可见度")

        def change(percent: int) -> None:
            self._active_opacity = percent / 100
            value.setText(f"{percent}%")
            self.update()

        slider.valueChanged.connect(change)
        layout.addWidget(label)
        layout.addWidget(slider, 1)
        layout.addWidget(value)
        action.setDefaultWidget(row)
        return action

    def _size_action(self, menu: QMenu) -> QWidgetAction:
        action = QWidgetAction(menu)
        row = QWidget(menu)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 5, 12, 7)
        label = QLabel("窗口大小", row)
        value = QLabel(f"{self._scale_percent}%", row)
        value.setMinimumWidth(34)
        slider = QSlider(Qt.Orientation.Horizontal, row)
        slider.setRange(60, 160)
        slider.setSingleStep(5)
        slider.setPageStep(10)
        slider.setValue(self._scale_percent)
        slider.setMinimumWidth(145)
        slider.setToolTip("等比例调节悬浮窗与钢琴键盘大小")

        def change(percent: int) -> None:
            self._set_scale(percent)
            value.setText(f"{percent}%")

        slider.valueChanged.connect(change)
        layout.addWidget(label)
        layout.addWidget(slider, 1)
        layout.addWidget(value)
        action.setDefaultWidget(row)
        return action

    def _set_scale(self, percent: int) -> None:
        percent = max(60, min(160, percent))
        if percent == self._scale_percent:
            return
        center = self.frameGeometry().center()
        self._scale_percent = percent
        base_width, base_height = (
            (self.config.height, self.config.width)
            if self._erhu_vertical
            else (self.config.width, self.config.height)
        )
        width = round(base_width * percent / 100)
        height = round(base_height * percent / 100)
        self.setFixedSize(width, height)
        self.move(center.x() - width // 2, center.y() - height // 2)
        self.update()

    def restore_settings(self) -> None:
        settings = QSettings("Piano Shadow", "Piano Shadow")
        self._opacity = max(
            0.0, min(1.0, float(settings.value("keyboard_opacity", 0.85)))
        )
        self._active_opacity = max(
            0.30, min(1.0, float(settings.value("active_opacity", 0.85)))
        )
        # Visual mode intentionally starts from Piano on every launch. A
        # previous Erhu session must not silently load the melody model.
        self._visual_mode = "piano"
        self._scale_percent = max(
            60, min(160, int(settings.value("scale_percent", 100)))
        )
        self.setFixedSize(
            round(self.config.width * self._scale_percent / 100),
            round(self.config.height * self._scale_percent / 100),
        )
        saved_position = settings.value("position", None)
        if isinstance(saved_position, QPoint):
            candidate = QRect(
                saved_position.x(),
                saved_position.y(),
                self.width(),
                self.height(),
            )
            if any(
                screen.availableGeometry().intersects(candidate)
                for screen in QApplication.screens()
            ):
                self.move(saved_position)
        self.config.model = "piano-gpu"
        self._instrument_index = max(
            0,
            min(
                len(INSTRUMENTS) - 1,
                int(settings.value("performance_instrument", 0)),
            ),
        )
        saved_source = str(
            settings.value("performance_sound_source", "windows")
        )
        self._sound_source = (
            "soundfont"
            if saved_source == "soundfont" and self._soundfont_is_installed()
            else "windows"
        )
        self._always_on_top = settings.value(
            "always_on_top", True, type=bool
        )
        self._keyboard_only = settings.value(
            "keyboard_only", False, type=bool
        )
        self._position_locked = settings.value(
            "position_locked", self._keyboard_only, type=bool
        )
        self._toggle_click_through(self._position_locked)
        self.setCursor(
            Qt.CursorShape.ArrowCursor
            if self._position_locked
            else Qt.CursorShape.OpenHandCursor
        )
        self._toggle_topmost(self._always_on_top)
        self.update()

    def save_settings(self) -> None:
        settings = QSettings("Piano Shadow", "Piano Shadow")
        settings.setValue("position", self.pos())
        settings.setValue("scale_percent", self._scale_percent)
        settings.setValue("keyboard_opacity", self._opacity)
        settings.setValue("active_opacity", self._active_opacity)
        settings.setValue(
            "performance_instrument", self._instrument_index
        )
        settings.setValue(
            "performance_sound_source", self._sound_source
        )
        settings.setValue("always_on_top", self._always_on_top)
        settings.setValue("position_locked", self._position_locked)
        settings.setValue("keyboard_only", self._keyboard_only)
        settings.sync()

    def reset_settings(self) -> None:
        answer = QMessageBox.question(
            self,
            "恢复默认设置",
            "确定恢复窗口位置、大小、透明度和功能状态的默认值吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        old_model = self.config.model
        self._opacity = 0.85
        self._active_opacity = 0.85
        self._visual_mode = "piano"
        self._erhu_vertical = False
        self._erhu_history = True
        self._erhu_body = True
        self._erhu_mapper.reset()
        self._erhu_state = None
        self._erhu_trails.clear()
        self._scale_percent = 100
        self._instrument_index = 0
        self._sound_source = "windows"
        if self._performance is not None:
            self._performance.instrument_index = 0
            self._performance.use_windows()
            self._performance.synth.set_program(0)
        self._keyboard_only = False
        self._position_locked = False
        self._toggle_click_through(False)
        self._toggle_topmost(True)
        self.setFixedSize(self.config.width, self.config.height)
        screen = QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(
                area.center().x() - self.width() // 2,
                area.center().y() - self.height() // 2,
            )
        self.config.model = "piano-gpu"
        if old_model != self.config.model:
            self.model_selected.emit(self.config.model)
        QSettings("Piano Shadow", "Piano Shadow").clear()
        self.save_settings()
        self.set_status("已恢复默认设置", False)
        self.update()

    def _toggle_topmost(self, enabled: bool) -> None:
        if platform.system() == "Windows":
            self._always_on_top = enabled
            self._set_windows_topmost(enabled)
            self.update()
            return
        if enabled == self._always_on_top:
            if enabled:
                self._maintain_topmost()
            self.update()
            return
        old_position = self.pos()
        self._always_on_top = enabled
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.show()
        self.move(old_position)
        # WSLg/XWayland may apply placement once more after show().
        QTimer.singleShot(0, lambda position=old_position: self.move(position))
        if enabled:
            QTimer.singleShot(0, self._maintain_topmost)
        self.update()

    def _maintain_topmost(self) -> None:
        """Reassert stacking without activating/focusing or rebuilding the window."""
        if self._always_on_top and self.isVisible():
            if platform.system() == "Windows":
                self._set_windows_topmost(True)
            else:
                self.raise_()

    def _set_windows_topmost(self, enabled: bool) -> None:
        """Use Win32 SetWindowPos without moving or recreating the Qt window."""
        if platform.system() != "Windows":
            return
        try:
            import ctypes
            from ctypes import wintypes

            hwnd_topmost = -1
            hwnd_notopmost = -2
            flags = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
            set_window_pos = ctypes.windll.user32.SetWindowPos
            set_window_pos.argtypes = (
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            )
            set_window_pos.restype = wintypes.BOOL
            result = set_window_pos(
                wintypes.HWND(int(self.winId())),
                wintypes.HWND(hwnd_topmost if enabled else hwnd_notopmost),
                0,
                0,
                0,
                0,
                flags,
            )
            if not result:
                raise ctypes.WinError()
        except Exception as exc:
            self.set_status(f"Windows 置顶切换失败（{exc}）", True)

    def _toggle_position_lock(self, enabled: bool) -> None:
        self._position_locked = enabled
        self._drag_offset = None
        self._toggle_click_through(enabled)
        self.setCursor(
            Qt.CursorShape.ArrowCursor if enabled else Qt.CursorShape.OpenHandCursor
        )

    def _toggle_click_through(self, enabled: bool) -> None:
        self._click_through = enabled
        if platform.system() == "Windows":
            try:
                import ctypes
                from ctypes import wintypes

                hwnd = wintypes.HWND(int(self.winId()))
                get_style = ctypes.windll.user32.GetWindowLongPtrW
                set_style = ctypes.windll.user32.SetWindowLongPtrW
                get_style.argtypes = (wintypes.HWND, ctypes.c_int)
                get_style.restype = ctypes.c_ssize_t
                set_style.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
                set_style.restype = ctypes.c_ssize_t
                ex_style = get_style(hwnd, -20)  # GWL_EXSTYLE
                ws_ex_transparent = 0x00000020
                ws_ex_layered = 0x00080000
                # Whole-window WS_EX_TRANSPARENT would also disable the lock
                # button. Selective passthrough is handled in nativeEvent.
                ex_style |= ws_ex_layered
                ex_style &= ~ws_ex_transparent
                set_style(hwnd, -20, ex_style)
                set_window_pos = ctypes.windll.user32.SetWindowPos
                set_window_pos.argtypes = (
                    wintypes.HWND,
                    wintypes.HWND,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    wintypes.UINT,
                )
                set_window_pos.restype = wintypes.BOOL
                set_window_pos(
                    hwnd,
                    wintypes.HWND(0),
                    0,
                    0,
                    0,
                    0,
                    0x0001 | 0x0002 | 0x0010 | 0x0020,
                )
                self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                return
            except Exception as exc:
                self.set_status(f"Windows 鼠标穿透切换失败（{exc}）", True)
        # Qt has no portable per-pixel input passthrough. Keep the lock button
        # usable on non-Windows platforms instead of making unlock impossible.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

    def _toggle_keyboard_only(self, enabled: bool) -> None:
        self._keyboard_only = enabled
        # Entering is always locked; leaving restores normal draggable mode.
        self._toggle_position_lock(enabled)
        self.update()
