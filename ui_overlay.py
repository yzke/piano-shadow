"""Frameless translucent desktop overlay and animations."""

from __future__ import annotations

import math
import platform
import time
from dataclasses import dataclass

from PyQt6.QtCore import QLineF, QPoint, QRectF, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSlider,
    QWidget,
    QWidgetAction,
)

from config import AppConfig
from note_model import NoteEvent, PIANO_HIGH, PIANO_LOW, is_black_key

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


@dataclass(slots=True)
class VisualNote:
    midi: int
    born: float
    strength: float
    name: str
    lane: int


class OverlayWindow(QWidget):
    notes_received = pyqtSignal(object)
    status_received = pyqtSignal(str, bool)
    model_selected = pyqtSignal(str)
    model_fallback_received = pyqtSignal(str)

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.visual_notes: list[VisualNote] = []
        self.status_text = "Piano Shadow · Starting…"
        self.status_error = False
        self._drag_offset: QPoint | None = None
        self._native_move = False
        self._always_on_top = True
        self._position_locked = False
        self._click_through = False
        self._show_status = True
        self._opacity = 0.85
        self._scale_percent = 100
        self._setup_window()
        self.notes_received.connect(self.add_notes)
        self.status_received.connect(self.set_status)
        self.model_fallback_received.connect(self._handle_model_fallback)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)
        self._topmost_timer = QTimer(self)
        self._topmost_timer.setInterval(800)
        self._topmost_timer.timeout.connect(self._maintain_topmost)
        self._topmost_timer.start()

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
        if not events:
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

    def set_status(self, text: str, error: bool = False) -> None:
        self.status_text = text
        self.status_error = error
        self.update()

    def _tick(self) -> None:
        now = time.monotonic()
        self.visual_notes = [
            n for n in self.visual_notes if now - n.born < self.config.decay_seconds * 1.35
        ]
        if self.visual_notes:
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
                    margin + white_index * white_width, top, white_width - 0.65, height
                )
                white_index += 1
        return white, black

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # WSLg/Wayland may ignore window-manager opacity for translucent
        # frameless windows. Paint-level opacity is platform-independent.
        painter.setOpacity(self._opacity)
        now = time.monotonic()
        self._draw_glass(painter)
        self._draw_status(painter)
        self._draw_settings(painter)
        self._draw_pitch_legend(painter)
        self._draw_controls(painter)
        white, black = self._keyboard_geometry()
        self._draw_note_labels(painter, now, white, black)
        self._draw_keyboard(painter, white, black, now)

    def _draw_glass(self, p: QPainter) -> None:
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

    def _draw_settings(self, p: QPainter) -> None:
        if not self._show_status or self.width() < 700:
            return
        text = (
            f"CHUNK {self.config.chunk_seconds:g}s   "
            f"DECAY {self.config.decay_seconds:g}s   "
            f"AMP {self.config.min_amp:g}"
        )
        font = QFont("Inter, Arial, sans-serif", 7)
        p.setFont(font)
        p.setPen(QColor(176, 197, 218, 125))
        p.drawText(
            QRectF(self.width() * 0.30, 17, self.width() * 0.28, 24),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            text,
        )

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

    def _control_rects(self) -> dict[str, QRectF]:
        size = max(21.0, min(27.0, self.height() * 0.17))
        gap = 5.0
        names = ("model", "lock", "top", "smaller", "larger", "opacity")
        start = self.width() - 20.0 - len(names) * size - (len(names) - 1) * gap
        return {
            name: QRectF(start + index * (size + gap), 16.0, size, size)
            for index, name in enumerate(names)
        }

    def _draw_controls(self, p: QPainter) -> None:
        p.save()
        for name, rect in self._control_rects().items():
            active = (
                (name == "lock" and self._position_locked)
                or (name == "top" and self._always_on_top)
                or (name == "model" and self.config.model == "piano-gpu")
            )
            p.setPen(QPen(QColor(132, 208, 246, 105) if active else QColor(255, 255, 255, 25)))
            p.setBrush(QColor(61, 139, 186, 90) if active else QColor(19, 29, 45, 155))
            p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
            self._draw_control_icon(p, name, rect)
        p.restore()

    def _draw_control_icon(self, p: QPainter, name: str, rect: QRectF) -> None:
        cx, cy = rect.center().x(), rect.center().y()
        unit = rect.width() / 8.0
        p.setPen(QPen(QColor(205, 233, 249, 225), max(1.2, unit * 0.48)))
        p.setBrush(Qt.BrushStyle.NoBrush)

        if name == "model":
            chip = QRectF(cx - 2.15 * unit, cy - 1.75 * unit, 4.3 * unit, 3.5 * unit)
            p.drawRoundedRect(chip, unit * 0.45, unit * 0.45)
            for offset in (-1.25, 0, 1.25):
                p.drawLine(QLineF(cx + offset * unit, cy - 2.45 * unit, cx + offset * unit, cy - 1.75 * unit))
                p.drawLine(QLineF(cx + offset * unit, cy + 1.75 * unit, cx + offset * unit, cy + 2.45 * unit))
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
        elif name == "opacity":
            circle = QRectF(cx - 2.25 * unit, cy - 2.25 * unit, 4.5 * unit, 4.5 * unit)
            p.drawEllipse(circle)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(205, 233, 249, 210))
            p.drawPie(circle, 90 * 16, 180 * 16)

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
            p.setPen(QPen(guide, 0.8))
            p.drawLine(
                QLineF(
                    center_x,
                    solfege_y + 2,
                    key_rect.center().x(),
                    keyboard_top - 3,
                )
            )
            p.setFont(font)
            p.setPen(self._note_color(note.midi, round(245 * alpha)))
            p.drawText(QPoint(round(center_x - note_width / 2), round(y)), note.name)
            p.setFont(solfege_font)
            p.setPen(self._note_color(note.midi, round(185 * alpha)))
            p.drawText(
                QPoint(round(center_x - solfege_width / 2), round(solfege_y)),
                solfege,
            )

    def _draw_keyboard(self, p: QPainter, white, black, now: float) -> None:
        active: dict[int, float] = {}
        for note in self.visual_notes:
            active[note.midi] = max(active.get(note.midi, 0), self._alpha(note, now) * note.strength)
        self._draw_active_auras(p, white, black, active)
        for midi, rect in white.items():
            glow = active.get(midi, 0)
            base = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            # Resting keys sit roughly 10 percentage points above the glass.
            base.setColorAt(0, QColor(230, 237, 246, 255))
            base.setColorAt(1, QColor(154, 170, 190, 250))
            if glow:
                color = self._note_color(midi)
                # White keys use the former black-key treatment: saturated
                # center, stronger contrast and a deeper colored tail.
                light = color.lighter(125)
                deep = color.darker(165)
                alpha = round(185 + 70 * glow)
                light.setAlpha(alpha)
                color.setAlpha(alpha)
                deep.setAlpha(round(alpha * 0.97))
                base.setColorAt(0, light)
                base.setColorAt(0.42, color)
                base.setColorAt(1, deep)
            edge = self._note_color(midi, round(58 + 90 * glow))
            p.setPen(QPen(edge, 0.8))
            p.setBrush(base)
            if glow:
                p.save()
                p.setOpacity(max(0.50, self._opacity))
                p.drawRoundedRect(rect, 1.8, 1.8)
                p.restore()
            else:
                p.drawRoundedRect(rect, 1.8, 1.8)
        # Glows are batched only for active keys.
        p.save()
        p.setOpacity(max(0.50, self._opacity))
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        for midi, strength in active.items():
            rect = white.get(midi)
            if rect is None:
                rect = black.get(midi)
            if rect is None:
                continue
            center = rect.center()
            color = self._note_color(midi)
            mid = color.lighter(112)
            radius = max(18, rect.width() * 3.0)
            glow = QRadialGradient(center, radius)
            mid.setAlpha(round(145 * strength))
            transparent = self._note_color(midi, 0)
            color.setAlpha(round(235 * strength))
            glow.setColorAt(0, color)
            glow.setColorAt(0.38, mid)
            glow.setColorAt(1, transparent)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(center, radius, radius)
        p.restore()
        for midi, rect in black.items():
            glow = active.get(midi, 0)
            base = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            base.setColorAt(0, QColor(42, 52, 68, 255))
            base.setColorAt(1, QColor(8, 14, 25, 250))
            if glow:
                color = self._note_color(midi)
                # Black keys use the former white-key treatment: a softer,
                # brighter glass tint with less dark color compression.
                light = color.lighter(150)
                deep = color.darker(118)
                alpha = round(160 + 70 * glow)
                light.setAlpha(alpha)
                color.setAlpha(alpha)
                deep.setAlpha(round(alpha * 0.86))
                base.setColorAt(0, light)
                base.setColorAt(0.48, color)
                base.setColorAt(1, deep)
            edge = self._note_color(midi, round(30 + 110 * glow))
            p.setPen(QPen(edge, 0.7))
            p.setBrush(base)
            if glow:
                p.save()
                p.setOpacity(max(0.50, self._opacity))
                p.drawRoundedRect(rect, 2, 2)
                p.restore()
            else:
                p.drawRoundedRect(rect, 2, 2)
        self._draw_active_key_edges(p, white, black, active)

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
        p.setOpacity(max(0.50, self._opacity))
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
        p.setOpacity(max(0.50, self._opacity))
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
            p.drawRoundedRect(rect.adjusted(0.7, 0.7, -0.7, -0.7), 2, 2)
            p.setPen(QPen(self._note_color(midi, round(245 * strength)), 1.8))
            p.drawLine(QLineF(rect.left() + 1.5, rect.top() + 1.2, rect.right() - 1.5, rect.top() + 1.2))
        p.restore()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            control = self._control_at(event.position())
            if control:
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

    def _control_at(self, point) -> str | None:
        for name, rect in self._control_rects().items():
            if rect.contains(point):
                return name
        return None

    def _begin_move(self, event: QMouseEvent) -> None:
        self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        handle = self.windowHandle()
        self._native_move = bool(handle and handle.startSystemMove())
        event.accept()

    def _activate_control(self, name: str) -> None:
        if name == "model":
            next_model = (
                "basic-pitch"
                if self.config.model == "piano-gpu"
                else "piano-gpu"
            )
            self._select_model(next_model)
        elif name == "lock":
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
        elif name == "opacity":
            levels = (20, 30, 40, 50, 60, 70, 80, 85, 90, 95, 100)
            current = round(self._opacity * 100)
            next_level = next((level for level in levels if level > current), 20)
            self._opacity = next_level / 100
        self.update()

    def _show_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        top = QAction("始终置顶", self, checkable=True, checked=self._always_on_top)
        top.triggered.connect(self._toggle_topmost)
        locked = QAction("锁定位置", self, checkable=True, checked=self._position_locked)
        locked.triggered.connect(self._toggle_position_lock)
        through = QAction("点击穿透", self, checkable=True, checked=self._click_through)
        through.triggered.connect(self._toggle_click_through)
        status = QAction("显示参数面板", self, checkable=True, checked=self._show_status)
        status.triggered.connect(lambda checked: self._set_show_status(checked))
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(top)
        menu.addAction(locked)
        menu.addAction(through)
        menu.addSeparator()
        model_menu = menu.addMenu("识别模型")
        model_group = QActionGroup(model_menu)
        model_group.setExclusive(True)
        for title, model_name in (
            ("Basic Pitch · 快速通用", "basic-pitch"),
            ("Piano GPU · 钢琴高精度", "piano-gpu"),
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
        menu.addAction(self._opacity_action(menu))
        menu.addAction(self._size_action(menu))
        menu.addAction(status)
        menu.addSeparator()
        menu.addAction(quit_action)
        menu.exec(position)

    def _select_model(self, model_name: str) -> None:
        if model_name == self.config.model:
            return
        self.config.model = model_name
        self.model_selected.emit(model_name)
        self.update()

    @pyqtSlot(str)
    def _handle_model_fallback(self, model_name: str) -> None:
        if self.config.model != model_name:
            self._select_model(model_name)

    def _opacity_action(self, menu: QMenu) -> QWidgetAction:
        action = QWidgetAction(menu)
        row = QWidget(menu)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 5, 12, 7)
        label = QLabel("透明度", row)
        value = QLabel(f"{round(self._opacity * 100)}%", row)
        value.setMinimumWidth(34)
        slider = QSlider(Qt.Orientation.Horizontal, row)
        slider.setRange(20, 100)
        slider.setValue(round(self._opacity * 100))
        slider.setMinimumWidth(145)
        slider.setToolTip("调节整个悬浮窗的可见度")

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
        width = round(self.config.width * percent / 100)
        height = round(self.config.height * percent / 100)
        self.setFixedSize(width, height)
        self.move(center.x() - width // 2, center.y() - height // 2)
        self.update()

    def _toggle_topmost(self, enabled: bool) -> None:
        if platform.system() == "Windows":
            self._always_on_top = enabled
            self._set_windows_topmost(enabled)
            if enabled:
                self._topmost_timer.start()
            else:
                self._topmost_timer.stop()
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
            self._topmost_timer.start()
            QTimer.singleShot(0, self._maintain_topmost)
        else:
            self._topmost_timer.stop()
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
        self.setCursor(
            Qt.CursorShape.ArrowCursor if enabled else Qt.CursorShape.OpenHandCursor
        )

    def _toggle_click_through(self, enabled: bool) -> None:
        self._click_through = enabled
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, enabled)
        self.show()

    def _set_show_status(self, enabled: bool) -> None:
        self._show_status = enabled
        self.update()
