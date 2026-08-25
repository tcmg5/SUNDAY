"""Custom-painted instrument widgets.

Qt stylesheets handle panels and buttons; everything with a curve, a glow or a
needle is painted here. Each widget owns its own animation timer and exposes a
small setter API so the dashboard can push live values in without knowing how
any of it is drawn.
"""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QSizePolicy,
    QVBoxLayout, QWidget,
)

from .theme import C, M, font


def _c(hex_color: str, alpha: int = 255) -> QColor:
    col = QColor(hex_color)
    col.setAlpha(alpha)
    return col


# ══ containers ═══════════════════════════════════════════════════════════
class Panel(QFrame):
    """A titled card with clipped corner accents - the base unit of the grid."""

    def __init__(self, title: str = "", action: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(M.pad, M.pad - 2, M.pad, M.pad)
        self._layout.setSpacing(9)

        if title:
            head = QHBoxLayout()
            head.setSpacing(8)
            label = QLabel(title.upper())
            label.setObjectName("PanelTitle")
            label.setFont(font(11, 700, "display", spacing=1.4))
            head.addWidget(label)
            head.addStretch()
            if action:
                self.action = QLabel(action)
                self.action.setFont(font(11, 500))
                self.action.setStyleSheet(f"color: {C.CYAN_DIM};")
                self.action.setCursor(Qt.PointingHandCursor)
                head.addWidget(self.action)
            self._layout.addLayout(head)

    def body(self) -> QVBoxLayout:
        return self._layout

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(_c(C.CYAN, 120))
        pen.setWidthF(1.4)
        p.setPen(pen)
        w, h, n = self.width(), self.height(), 14
        # Corner brackets: the cheapest way to read as "instrument panel".
        for x0, y0, dx, dy in ((1, 1, 1, 1), (w - 1, 1, -1, 1),
                               (1, h - 1, 1, -1), (w - 1, h - 1, -1, -1)):
            p.drawLine(x0, y0 + dy * 2, x0, y0 + dy * n)
            p.drawLine(x0 + dx * 2, y0, x0 + dx * n, y0)
        p.end()


class GridBackground(QWidget):
    """The faint blueprint grid and vignette behind the whole dashboard."""

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        base = QLinearGradient(0, 0, w * 0.4, h)
        base.setColorAt(0.0, _c("#071120"))
        base.setColorAt(0.5, _c(C.DEEP))
        base.setColorAt(1.0, _c(C.VOID))
        p.fillRect(0, 0, w, h, QBrush(base))

        pen = QPen(_c(C.CYAN, 12))
        pen.setWidth(1)
        p.setPen(pen)
        step = 46
        for x in range(0, w, step):
            p.drawLine(x, 0, x, h)
        for y in range(0, h, step):
            p.drawLine(0, y, w, y)

        # Corner glows, so the flat grid doesn't read as a spreadsheet.
        for cx, cy, colour, alpha in ((0, h, C.CYAN, 26), (w, 0, C.BLUE, 20)):
            glow = QRadialGradient(QPointF(cx, cy), max(w, h) * 0.55)
            glow.setColorAt(0.0, _c(colour, alpha))
            glow.setColorAt(1.0, _c(colour, 0))
            p.fillRect(0, 0, w, h, QBrush(glow))
        p.end()


# ══ the centrepiece ══════════════════════════════════════════════════════
class HoloGlobe(QWidget):
    """Wireframe sphere with orbital rings and drifting nodes.

    Latitude/longitude lines are projected from real 3-D coordinates rotating
    about the Y axis, so the sphere genuinely turns rather than looping a
    2-D animation. Speed and colour follow the assistant's state.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._phase = 0.0
        self._level = 0.0
        self._target = 0.0
        self._colour = QColor(C.CYAN)
        self._speed = 0.004
        self._title = "JARVIS"
        self._subtitle = "AI CORE"
        self._version = "v1.0.0"
        # Fixed node positions on the sphere, so they rotate with it.
        rng = random.Random(7)
        self._nodes = [
            (rng.uniform(0, math.tau), math.asin(rng.uniform(-1, 1)))
            for _ in range(34)
        ]
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(33)

    def _tick(self):
        self._phase += self._speed
        self._level += (self._target - self._level) * 0.18
        self.update()

    def set_level(self, level: float):
        self._target = max(0.0, min(1.0, float(level)))

    def set_accent(self, hex_colour: str, speed: float):
        self._colour = QColor(hex_colour)
        self._speed = speed

    def set_identity(self, title: str, subtitle: str, version: str):
        self._title, self._subtitle, self._version = title, subtitle, version

    # -- projection ------------------------------------------------------
    def _project(self, lon: float, lat: float, r: float, cx: float, cy: float):
        """Rotate about Y by the current phase, then project orthographically."""
        x = math.cos(lat) * math.sin(lon + self._phase)
        y = math.sin(lat)
        z = math.cos(lat) * math.cos(lon + self._phase)
        return QPointF(cx + x * r, cy - y * r), z

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) * 0.27 * (1.0 + 0.05 * self._level)
        col = self._colour

        # Atmosphere
        halo = QRadialGradient(QPointF(cx, cy), r * 2.3)
        halo.setColorAt(0.0, _c(col.name(), int(30 + 40 * self._level)))
        halo.setColorAt(0.45, _c(col.name(), 16))
        halo.setColorAt(1.0, _c(col.name(), 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(halo))
        p.drawEllipse(QPointF(cx, cy), r * 2.3, r * 2.3)

        # Filled core so the wireframe reads as a solid body
        core = QRadialGradient(QPointF(cx - r * 0.3, cy - r * 0.3), r * 1.8)
        core.setColorAt(0.0, _c("#0E3A52", 190))
        core.setColorAt(0.6, _c("#07202F", 170))
        core.setColorAt(1.0, _c("#04121C", 210))
        p.setBrush(QBrush(core))
        p.drawEllipse(QPointF(cx, cy), r, r)

        # Latitude rings - flatten to ellipses, brighter toward the equator
        for i in range(1, 10):
            lat = -math.pi / 2 + i * math.pi / 10
            ry = r * math.cos(lat)
            y = cy - math.sin(lat) * r
            alpha = int(58 + 72 * math.cos(lat))
            pen = QPen(_c(col.name(), alpha))
            pen.setWidthF(1.0)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(cx - r * math.cos(lat), y - ry * 0.30, ry * 2, ry * 0.60))

        # Longitude arcs - only the front-facing half, so it looks 3-D
        for i in range(16):
            lon = i * math.pi / 8
            path = QPainterPath()
            started = False
            for step in range(41):
                lat = -math.pi / 2 + step * math.pi / 40
                point, z = self._project(lon, lat, r, cx, cy)
                if z < 0:
                    started = False
                    continue
                path.moveTo(point) if not started else path.lineTo(point)
                started = True
            pen = QPen(_c(col.name(), 78))
            pen.setWidthF(1.0)
            p.setPen(pen)
            p.drawPath(path)

        # Surface nodes, with the far side dimmed
        for lon, lat in self._nodes:
            point, z = self._project(lon, lat, r, cx, cy)
            if z < -0.15:
                continue
            depth = (z + 1) / 2
            size = 1.2 + 2.0 * depth + self._level * 1.6
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(_c(C.CYAN_BRIGHT, int(70 + 165 * depth))))
            p.drawEllipse(point, size, size)

        # Orbital rings, tilted, one counter-rotating
        for idx, (scale, tilt, direction, alpha) in enumerate(
            ((1.22, 0.26, 1, 120), (1.42, 0.44, -1, 84), (1.58, 0.15, 1, 56))
        ):
            p.save()
            p.translate(cx, cy)
            p.rotate(math.degrees(self._phase * direction * 0.6) + idx * 34)
            pen = QPen(_c(col.name(), alpha))
            pen.setWidthF(1.2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            rx, ry = r * scale, r * scale * tilt
            p.drawEllipse(QRectF(-rx, -ry, rx * 2, ry * 2))
            # A satellite riding each ring
            angle = self._phase * direction * 2.2 + idx * 2.1
            sx, sy = math.cos(angle) * rx, math.sin(angle) * ry
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(_c(C.CYAN_BRIGHT, 220)))
            p.drawEllipse(QPointF(sx, sy), 2.6, 2.6)
            p.restore()

        # Identity block
        p.setPen(_c(C.TEXT, 240))
        p.setFont(font(int(min(w, h) * 0.115), 700, "display", spacing=7))
        p.drawText(QRectF(0, cy - r * 0.42, w, r * 0.5), Qt.AlignCenter, self._title)
        p.setPen(_c(C.CYAN, 200))
        p.setFont(font(int(min(w, h) * 0.045), 500, "display", spacing=6))
        p.drawText(QRectF(0, cy + r * 0.12, w, r * 0.3), Qt.AlignCenter, self._subtitle)
        p.setPen(_c(C.TEXT_FAINT, 200))
        p.setFont(font(11, 400, "mono"))
        p.drawText(QRectF(0, cy + r * 0.46, w, 20), Qt.AlignCenter, self._version)
        p.end()


# ══ instruments ══════════════════════════════════════════════════════════
class DonutGauge(QWidget):
    """Ring gauge for CPU / RAM / disk. Colour shifts as it approaches full."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._value = 0.0
        self._shown = 0.0
        self.setMinimumSize(84, 96)
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(40)

    def _tick(self):
        if abs(self._shown - self._value) > 0.15:
            self._shown += (self._value - self._shown) * 0.16
            self.update()

    def set_value(self, percent: float):
        self._value = max(0.0, min(100.0, float(percent)))

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        size = min(w, h - 18)
        cx, cy, r = w / 2, (h - 18) / 2 + 2, size / 2 - 7

        colour = C.CYAN if self._shown < 70 else (C.AMBER if self._shown < 88 else C.RED)

        pen = QPen(_c(C.EDGE_LIT, 150))
        pen.setWidthF(6.5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), 90 * 16, -360 * 16)

        span = int(-self._shown / 100 * 360 * 16)
        glow = QPen(_c(colour, 55))
        glow.setWidthF(12.0)
        glow.setCapStyle(Qt.RoundCap)
        p.setPen(glow)
        p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), 90 * 16, span)

        pen = QPen(_c(colour, 255))
        pen.setWidthF(6.5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), 90 * 16, span)

        p.setPen(_c(C.TEXT_MUTED, 220))
        p.setFont(font(10, 600, "display", spacing=1.0))
        p.drawText(QRectF(0, cy - 17, w, 14), Qt.AlignCenter, self._label.upper())
        p.setPen(_c(C.TEXT, 255))
        p.setFont(font(17, 700, "mono"))
        p.drawText(QRectF(0, cy - 1, w, 22), Qt.AlignCenter, f"{self._shown:.0f}%")
        p.end()


class WaveBars(QWidget):
    """Compact bar-style waveform. Idles as a low shimmer, spikes on level."""

    def __init__(self, colour: str = C.CYAN, bars: int = 30, parent=None):
        super().__init__(parent)
        self._colour = colour
        self._n = bars
        self._values = [0.05] * bars
        self._level = 0.0
        self._active = False
        self._t = 0.0
        self.setMinimumHeight(26)
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(55)

    def _tick(self):
        self._t += 0.35
        for i in range(self._n):
            if self._active:
                # Envelope peaks mid-span so it reads as a voice, not a bar chart.
                envelope = math.sin(math.pi * (i + 0.5) / self._n) ** 0.6
                target = envelope * (
                    0.25 + 0.75 * self._level
                ) * (0.55 + 0.45 * math.sin(self._t * 1.7 + i * 0.55))
                target = abs(target)
            else:
                target = 0.04 + 0.05 * abs(math.sin(self._t * 0.35 + i * 0.4))
            self._values[i] += (target - self._values[i]) * 0.45
        self.update()

    def set_level(self, level: float):
        self._level = max(0.0, min(1.0, float(level)))

    def set_active(self, active: bool):
        self._active = active

    def set_colour(self, colour: str):
        self._colour = colour

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        slot = w / self._n
        bar = max(1.6, slot * 0.42)
        mid = h / 2
        for i, value in enumerate(self._values):
            amplitude = max(1.4, value * (h * 0.46))
            x = i * slot + (slot - bar) / 2
            alpha = int(90 + 165 * min(1.0, value * 2.4))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(_c(self._colour, alpha)))
            p.drawRoundedRect(QRectF(x, mid - amplitude, bar, amplitude * 2), bar / 2, bar / 2)
        p.end()


class MicOrb(QWidget):
    """The tap-to-speak orb: pulsing rings, brightens with mic level."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(120, 120)
        self.setCursor(Qt.PointingHandCursor)
        self._phase = 0.0
        self._level = 0.0
        self._shown = 0.0
        self._colour = QColor(C.CYAN)
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(33)

    def _tick(self):
        self._phase += 0.045
        self._shown += (self._level - self._shown) * 0.22
        self.update()

    def set_level(self, level: float):
        self._level = max(0.0, min(1.0, float(level)))

    def set_accent(self, hex_colour: str):
        self._colour = QColor(hex_colour)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        base = min(self.width(), self.height()) * 0.27
        col = self._colour

        # Expanding sonar rings
        for i in range(3):
            t = (self._phase * 0.5 + i / 3) % 1.0
            r = base * (1.0 + t * 1.5)
            alpha = int(85 * (1 - t) * (0.4 + 0.6 * self._shown))
            if alpha <= 0:
                continue
            pen = QPen(_c(col.name(), alpha))
            pen.setWidthF(1.5)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r, r)

        r = base * (1 + 0.10 * self._shown)
        glow = QRadialGradient(QPointF(cx, cy), r * 2.0)
        glow.setColorAt(0.0, _c(col.name(), int(110 + 90 * self._shown)))
        glow.setColorAt(1.0, _c(col.name(), 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy), r * 2.0, r * 2.0)

        body = QRadialGradient(QPointF(cx, cy - r * 0.3), r * 1.6)
        body.setColorAt(0.0, _c(C.CYAN_BRIGHT, 255))
        body.setColorAt(0.55, _c(col.name(), 235))
        body.setColorAt(1.0, _c(C.CYAN_DEEP, 220))
        p.setBrush(QBrush(body))
        p.drawEllipse(QPointF(cx, cy), r, r)

        # Microphone glyph
        p.setPen(QPen(_c("#04121C", 235), 2.4))
        p.setBrush(QBrush(_c("#04121C", 235)))
        cap = r * 0.30
        p.drawRoundedRect(QRectF(cx - cap / 2, cy - r * 0.46, cap, r * 0.62), cap / 2, cap / 2)
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(cx - r * 0.34, cy - r * 0.34, r * 0.68, r * 0.72), 180 * 16, 180 * 16)
        p.drawLine(QPointF(cx, cy + r * 0.38), QPointF(cx, cy + r * 0.56))
        p.end()


class Constellation(QWidget):
    """Memory graph: nodes drifting on linked paths. Density tracks memory count."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(96)
        self._t = 0.0
        self._count = 8
        self._seed_nodes(8)
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(60)

    def _seed_nodes(self, n: int):
        rng = random.Random(11)
        self._nodes = [
            (rng.uniform(0.06, 0.94), rng.uniform(0.12, 0.88),
             rng.uniform(0, math.tau), rng.uniform(0.4, 1.0))
            for _ in range(n)
        ]

    def set_count(self, memories: int):
        n = max(5, min(16, 5 + memories // 3))
        if n != self._count:
            self._count = n
            self._seed_nodes(n)

    def _tick(self):
        self._t += 0.02
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        points = []
        for fx, fy, phase, speed in self._nodes:
            x = fx * w + math.sin(self._t * speed + phase) * w * 0.022
            y = fy * h + math.cos(self._t * speed * 0.8 + phase) * h * 0.05
            points.append(QPointF(x, y))

        pen = QPen(_c(C.CYAN, 70))
        pen.setWidthF(1.0)
        p.setPen(pen)
        for i in range(len(points) - 1):
            p.drawLine(points[i], points[i + 1])
        # A couple of chords across the graph, so it reads as a network.
        for a, b in ((0, len(points) // 2), (1, len(points) - 2)):
            if 0 <= a < len(points) and 0 <= b < len(points):
                p.setPen(QPen(_c(C.CYAN, 34), 1.0))
                p.drawLine(points[a], points[b])

        for i, point in enumerate(points):
            pulse = 0.5 + 0.5 * math.sin(self._t * 2.0 + i)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(_c(C.CYAN, int(40 + 40 * pulse))))
            p.drawEllipse(point, 5.5, 5.5)
            p.setBrush(QBrush(_c(C.CYAN_BRIGHT, int(160 + 80 * pulse))))
            p.drawEllipse(point, 2.3, 2.3)
        p.end()


class Sparkline(QWidget):
    """Rolling history strip for the footer telemetry."""

    def __init__(self, colour: str = C.CYAN, points: int = 48, parent=None):
        super().__init__(parent)
        self._colour = colour
        self._n = points
        self._values = [0.0] * points
        self.setMinimumHeight(20)

    def push(self, value: float):
        self._values = (self._values + [max(0.0, min(1.0, value))])[-self._n:]
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        step = w / max(1, self._n - 1)
        path = QPainterPath()
        for i, value in enumerate(self._values):
            point = QPointF(i * step, h - 2 - value * (h - 5))
            path.moveTo(point) if i == 0 else path.lineTo(point)
        pen = QPen(_c(self._colour, 190))
        pen.setWidthF(1.4)
        p.setPen(pen)
        p.drawPath(path)
        p.end()


# ══ small composite rows ═════════════════════════════════════════════════
class StatusDot(QWidget):
    """A pulsing status dot. Pulse is reserved for live states only."""

    def __init__(self, colour: str = C.GREEN, pulse: bool = True, parent=None):
        super().__init__(parent)
        self._colour = colour
        self._pulse = pulse
        self._t = 0.0
        self.setFixedSize(10, 10)
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(60)

    def _tick(self):
        if self._pulse:
            self._t += 0.09
            self.update()

    def set_colour(self, colour: str, pulse: bool = True):
        self._colour, self._pulse = colour, pulse
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        amount = (0.5 + 0.5 * math.sin(self._t)) if self._pulse else 0.55
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(_c(self._colour, int(45 + 70 * amount))))
        p.drawEllipse(QPointF(cx, cy), 4.6, 4.6)
        p.setBrush(QBrush(_c(self._colour, 255)))
        p.drawEllipse(QPointF(cx, cy), 2.4, 2.4)
        p.end()


def glow(widget: QWidget, colour: str, radius: int = 26, alpha: int = 110) -> QWidget:
    """Attach an outer glow. Used sparingly - on the primary call to action."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(radius)
    effect.setColor(_c(colour, alpha))
    effect.setOffset(0, 0)
    widget.setGraphicsEffect(effect)
    return widget
