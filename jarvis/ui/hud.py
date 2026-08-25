"""The desktop HUD: a frameless, always-on-top panel you leave open.

Qt owns the main thread; the assistant runs on its own. Bus events therefore
arrive on the wrong thread, so everything crosses back through a Qt signal
(_event) before touching a widget.
"""
from __future__ import annotations

import logging
import math
import sys

from ..core.state import STATE_COLORS, STATE_LABELS, Event, State

log = logging.getLogger(__name__)

try:
    from PySide6.QtCore import QPoint, QPointF, Qt, QTimer, Signal
    from PySide6.QtGui import (
        QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
    )
    from PySide6.QtWidgets import (
        QApplication, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit,
        QVBoxLayout, QWidget,
    )
    QT_AVAILABLE = True
except ImportError:  # pragma: no cover
    QT_AVAILABLE = False


class ReactorRing(QWidget):
    """The arc reactor. Rotating arcs, pulse driven by mic level and state."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self._phase = 0.0
        self._level = 0.0
        self._target_level = 0.0
        self._color = QColor(STATE_COLORS[State.STARTING])
        self._state = State.STARTING
        timer = QTimer(self)
        timer.timeout.connect(self._advance)
        timer.start(33)  # ~30fps; enough for smooth rotation, cheap on battery

    def _advance(self):
        speed = {
            State.IDLE: 0.006,
            State.LISTENING: 0.03,
            State.THINKING: 0.05,
            State.SPEAKING: 0.02,
        }.get(self._state, 0.01)
        self._phase += speed
        # Ease toward the target so the ring breathes instead of twitching.
        self._level += (self._target_level - self._level) * 0.25
        self.update()

    def set_state(self, state: State):
        self._state = state
        self._color = QColor(STATE_COLORS.get(state, "#4FD3FF"))
        if state in (State.IDLE, State.THINKING):
            self._target_level = 0.0

    def set_level(self, level: float):
        self._target_level = max(0.0, min(1.0, float(level)))

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        base = min(w, h) * 0.34

        # Idle breathing, so it never looks frozen.
        breathe = 1.0 + 0.03 * math.sin(self._phase * 2.2)
        radius = base * breathe * (1.0 + 0.16 * self._level)

        # Outer glow
        glow = QRadialGradient(QPointF(cx, cy), radius * 2.1)
        c = QColor(self._color)
        c.setAlpha(int(70 + 90 * self._level))
        glow.setColorAt(0.0, c)
        glow.setColorAt(0.55, QColor(c.red(), c.green(), c.blue(), 26))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(QPointF(cx, cy), radius * 2.1, radius * 2.1)

        # Three counter-rotating arc sets
        for ring_index, (scale, span, width, direction) in enumerate((
            (1.42, 62, 2.0, 1),
            (1.18, 104, 3.0, -1),
            (0.94, 140, 2.0, 1),
        )):
            r = radius * scale
            pen = QPen(QColor(self._color))
            pen.setWidthF(width)
            pen.setCapStyle(Qt.RoundCap)
            alpha = 190 - ring_index * 35
            pen.setColor(QColor(self._color.red(), self._color.green(), self._color.blue(), alpha))
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            rect = (cx - r, cy - r, r * 2, r * 2)
            for arc in range(3):
                start = (self._phase * direction * 57.3 + arc * 120 + ring_index * 25)
                painter.drawArc(
                    int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]),
                    int(start * 16), int(span / 3 * 16),
                )

        # Tick marks - the "instrument" texture
        pen = QPen(QColor(self._color.red(), self._color.green(), self._color.blue(), 90))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        for i in range(48):
            angle = math.radians(i * 7.5)
            inner = radius * 0.62
            outer = radius * (0.72 if i % 4 else 0.80)
            painter.drawLine(
                QPointF(cx + math.cos(angle) * inner, cy + math.sin(angle) * inner),
                QPointF(cx + math.cos(angle) * outer, cy + math.sin(angle) * outer),
            )

        # Core
        core = QRadialGradient(QPointF(cx, cy), radius * 0.58)
        core.setColorAt(0.0, QColor(255, 255, 255, int(200 + 55 * self._level)))
        core.setColorAt(0.35, QColor(self._color.red(), self._color.green(), self._color.blue(), 210))
        core.setColorAt(1.0, QColor(self._color.red(), self._color.green(), self._color.blue(), 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(core))
        painter.drawEllipse(QPointF(cx, cy), radius * 0.58, radius * 0.58)

        # Live waveform ring while listening
        if self._level > 0.02:
            pen = QPen(QColor(255, 255, 255, 150))
            pen.setWidthF(1.6)
            painter.setPen(pen)
            path = QPainterPath()
            for i in range(73):
                angle = math.radians(i * 5)
                jitter = math.sin(i * 1.7 + self._phase * 8) * self._level * radius * 0.22
                r = radius * 0.86 + jitter
                point = QPointF(cx + math.cos(angle) * r, cy + math.sin(angle) * r)
                path.moveTo(point) if i == 0 else path.lineTo(point)
            painter.drawPath(path)
        painter.end()


class HUD(QWidget):
    _event = Signal(object)

    def __init__(self, assistant, cfg: dict):
        super().__init__()
        self.assistant = assistant
        self.cfg = cfg
        self._drag_offset: QPoint | None = None
        self._build()
        self._event.connect(self._on_event)
        assistant.bus.subscribe(lambda e: self._event.emit(e))

    def _build(self):
        ucfg = self.cfg["ui"]
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Tool  # keeps it out of the taskbar/dock
            | (Qt.WindowStaysOnTopHint if ucfg["always_on_top"] else Qt.Widget)
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowOpacity(ucfg["opacity"])
        self.resize(380, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)

        # Title bar
        header = QHBoxLayout()
        title = QLabel("J.A.R.V.I.S.")
        title.setFont(QFont("Helvetica Neue", 13, QFont.Bold))
        title.setStyleSheet(f"color: {ucfg['accent']}; letter-spacing: 4px;")
        header.addWidget(title)
        header.addStretch()
        self.mute_btn = self._chip("MUTE", self._toggle_mute)
        close_btn = self._chip("✕", self.close)
        header.addWidget(self.mute_btn)
        header.addWidget(close_btn)
        layout.addLayout(header)

        # Reactor
        self.ring = ReactorRing(self)
        layout.addWidget(self.ring)

        # State line
        self.status = QLabel(STATE_LABELS[State.STARTING])
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setFont(QFont("Helvetica Neue", 10, QFont.DemiBold))
        self.status.setStyleSheet("color: #8FA3B8; letter-spacing: 3px;")
        layout.addWidget(self.status)

        self.hint = QLabel('Say "hey JARVIS"')
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setStyleSheet("color: #5B6B7C; font-size: 11px;")
        layout.addWidget(self.hint)

        # Transcript
        self.feed = QTextEdit()
        self.feed.setReadOnly(True)
        self.feed.setStyleSheet(
            "QTextEdit { background: rgba(14,20,28,140); border: 1px solid rgba(79,211,255,45);"
            "border-radius: 10px; color: #C6D6E4; font-size: 12px; padding: 8px; }"
        )
        layout.addWidget(self.feed, stretch=1)

        # Typed input, for when speaking out loud isn't an option
        self.input = QLineEdit()
        self.input.setPlaceholderText("or type a command...")
        self.input.setStyleSheet(
            "QLineEdit { background: rgba(14,20,28,160); border: 1px solid rgba(79,211,255,55);"
            "border-radius: 8px; color: #E4EEF7; padding: 7px 10px; font-size: 12px; }"
            "QLineEdit:focus { border-color: rgba(79,211,255,140); }"
        )
        self.input.returnPressed.connect(self._submit)
        layout.addWidget(self.input)

        self._place(ucfg["position"])

    def _chip(self, text: str, handler) -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedHeight(22)
        btn.setStyleSheet(
            "QPushButton { background: rgba(79,211,255,22); color: #8FC6E0; border: none;"
            "border-radius: 11px; padding: 0 10px; font-size: 10px; letter-spacing: 1px; }"
            "QPushButton:hover { background: rgba(79,211,255,55); color: #E4F4FF; }"
        )
        btn.clicked.connect(handler)
        return btn

    def _place(self, position: str):
        screen = QApplication.primaryScreen().availableGeometry()
        margin = 28
        positions = {
            "bottom-right": (screen.right() - self.width() - margin, screen.bottom() - self.height() - margin),
            "bottom-left": (screen.left() + margin, screen.bottom() - self.height() - margin),
            "top-right": (screen.right() - self.width() - margin, screen.top() + margin),
            "center": (screen.center().x() - self.width() // 2, screen.center().y() - self.height() // 2),
        }
        x, y = positions.get(position, positions["bottom-right"])
        self.move(int(x), int(y))

    # -- painting ----------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 18, 18)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, QColor(11, 16, 23, 238))
        gradient.setColorAt(1.0, QColor(6, 10, 15, 245))
        painter.fillPath(path, QBrush(gradient))
        pen = QPen(QColor(79, 211, 255, 60))
        pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.end()

    # -- events ------------------------------------------------------------
    def _on_event(self, event: Event):
        if event.kind == "state":
            state = event.payload
            self.ring.set_state(state)
            self.status.setText(STATE_LABELS.get(state, str(state)))
            self.status.setStyleSheet(
                f"color: {STATE_COLORS.get(state, '#8FA3B8')}; letter-spacing: 3px;"
            )
            hints = {
                State.LISTENING: "Go ahead...",
                State.THINKING: "Working on it",
                State.SPEAKING: "",
                State.IDLE: 'Say "hey JARVIS"',
            }
            self.hint.setText(hints.get(state, ""))
        elif event.kind == "level":
            self.ring.set_level(event.payload)
        elif event.kind == "transcript":
            self._append("YOU", event.payload, "#7FD8FF")
        elif event.kind == "reply":
            self._append("JARVIS", event.payload, "#B8E6C4")
        elif event.kind == "tool":
            name, _args = event.payload
            self._append("·", name.replace("_", " "), "#6A7A8A", small=True)
        elif event.kind == "log":
            self._append("·", str(event.payload), "#5B6B7C", small=True)

    def _append(self, who: str, text: str, color: str, small: bool = False):
        size = "10px" if small else "12px"
        safe = str(text).replace("<", "&lt;").replace(">", "&gt;")
        self.feed.append(
            f'<div style="margin:3px 0;font-size:{size}">'
            f'<span style="color:{color};font-weight:600">{who}</span> '
            f'<span style="color:#C6D6E4">{safe}</span></div>'
        )
        self.feed.verticalScrollBar().setValue(self.feed.verticalScrollBar().maximum())

    def _submit(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        import threading

        threading.Thread(
            target=self.assistant.handle_text, args=(text,), daemon=True
        ).start()

    def _toggle_mute(self):
        muted = self.assistant.toggle_mute()
        self.mute_btn.setText("MUTED" if muted else "MUTE")

    # -- window dragging ---------------------------------------------------
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag_offset = None

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.close()

    def closeEvent(self, event):  # noqa: N802
        self.assistant.stop()
        event.accept()


def run_hud(assistant, cfg: dict) -> int:
    if not QT_AVAILABLE:
        raise RuntimeError("PySide6 is not installed. `pip install PySide6`, or use --ui console.")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    hud = HUD(assistant, cfg)
    hud.show()

    # Boot the assistant after the window is up, so BOOTING is actually visible.
    def boot():
        import threading

        threading.Thread(target=assistant.start, daemon=True).start()

    QTimer.singleShot(150, boot)
    return app.exec()
