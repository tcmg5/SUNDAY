"""Composite content rows used inside the dashboard panels.

These are ordinary layouts over the painted primitives in widgets.py - kept
separate so command_center.py reads as a floor plan rather than a pile of
widget construction.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .theme import C, font, rgba
from .widgets import StatusDot, WaveBars

# Glyphs come from the system emoji/symbol font - no icon pack to ship.
GLYPHS = {
    "command": "◈", "core": "◐", "agents": "⬡", "tasks": "▤", "calendar": "▦",
    "memory": "◇", "chat": "❐", "knowledge": "◎", "tools": "⚙", "flows": "⇄",
    "code": "</>", "search": "◯", "browser": "◍", "check": "✓", "system": "⬢",
    "mic": "◉", "bolt": "⚡", "play": "▶", "plus": "+", "clock": "◔",
}


class NavItem(QPushButton):
    """Sidebar entry: glyph, label, optional count badge."""

    def __init__(self, glyph: str, label: str, badge: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("NavItem")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(40)
        self.setFont(font(13, 500))
        # Qt reads a bare "&" as a mnemonic marker and swallows it.
        self.setText(f"  {glyph}    {label}".replace("&", "&&"))
        self._badge = QLabel(badge, self)
        self._badge.setFont(font(10, 700, "mono"))
        self._badge.setAlignment(Qt.AlignCenter)
        self._badge.setStyleSheet(
            f"background: {rgba(C.CYAN, 0.16)}; color: {C.CYAN};"
            f"border-radius: 8px; padding: 1px 7px;"
        )
        self._badge.setVisible(bool(badge))
        self.set_badge(badge)

    def set_badge(self, text: str):
        self._badge.setText(str(text))
        self._badge.setVisible(bool(text))
        self._badge.adjustSize()
        self._reposition_badge()

    def _reposition_badge(self):
        self._badge.move(self.width() - self._badge.width() - 12,
                         (self.height() - self._badge.height()) // 2)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._reposition_badge()


class SubsystemRow(QFrame):
    """One line of the AI Core Overview: glyph, name, live status text."""

    def __init__(self, glyph: str, name: str, colour: str = C.CYAN, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelInset")
        self.setFixedHeight(46)
        row = QHBoxLayout(self)
        row.setContentsMargins(9, 6, 10, 6)
        row.setSpacing(10)

        icon = QLabel(glyph)
        icon.setFixedSize(28, 28)
        icon.setAlignment(Qt.AlignCenter)
        icon.setFont(font(13))
        icon.setStyleSheet(
            f"background: {rgba(colour, 0.14)}; color: {colour};"
            f"border: 1px solid {rgba(colour, 0.30)}; border-radius: 7px;"
        )
        row.addWidget(icon)

        text = QVBoxLayout()
        text.setSpacing(0)
        self.name = QLabel(name)
        self.name.setFont(font(12, 600))
        self.name.setStyleSheet(f"color: {C.TEXT};")
        self.status = QLabel("...")
        self.status.setFont(font(10, 500))
        self.status.setStyleSheet(f"color: {C.TEXT_MUTED};")
        text.addWidget(self.name)
        text.addWidget(self.status)
        row.addLayout(text)
        row.addStretch()

    def set_status(self, text: str, colour: str = C.TEXT_MUTED):
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {colour};")


class AgentCard(QFrame):
    """An agent tile. Lights up when a tool in its group actually runs."""

    def __init__(self, glyph: str, name: str, colour: str, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelInset")
        self.setMinimumHeight(74)
        self._colour = colour
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 9, 10, 9)
        row.setSpacing(10)

        self.icon = QLabel(glyph)
        self.icon.setFixedSize(32, 32)
        self.icon.setAlignment(Qt.AlignCenter)
        self.icon.setFont(font(12, 600))
        self.icon.setStyleSheet(
            f"background: {rgba(colour, 0.14)}; color: {colour};"
            f"border: 1px solid {rgba(colour, 0.32)}; border-radius: 8px;"
        )
        row.addWidget(self.icon, alignment=Qt.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(3)
        title = QLabel(name)
        title.setFont(font(12, 600))
        title.setStyleSheet(f"color: {C.TEXT};")
        body.addWidget(title)

        state_row = QHBoxLayout()
        state_row.setSpacing(6)
        self.dot = StatusDot(C.TEXT_FAINT, pulse=False)
        self.state = QLabel("Standby")
        self.state.setFont(font(10, 500))
        self.state.setStyleSheet(f"color: {C.TEXT_MUTED};")
        state_row.addWidget(self.dot)
        state_row.addWidget(self.state)
        state_row.addStretch()
        body.addLayout(state_row)

        self.wave = WaveBars(colour, bars=22)
        self.wave.setFixedHeight(20)
        body.addWidget(self.wave)
        row.addLayout(body)

    def set_active(self, active: bool, label: str | None = None):
        self.wave.set_active(active)
        self.wave.set_level(0.75 if active else 0.0)
        self.dot.set_colour(self._colour if active else C.TEXT_FAINT, pulse=active)
        self.state.setText(label or ("Active" if active else "Standby"))
        self.state.setStyleSheet(f"color: {self._colour if active else C.TEXT_MUTED};")


class FeedItem(QFrame):
    """One entry in the Live Intelligence Feed."""

    KINDS = {
        "info": (C.BLUE, "INFO"),
        "live": (C.GREEN, "LIVE"),
        "warn": (C.AMBER, "WARN"),
        "error": (C.RED, "FAULT"),
        "tip": (C.PURPLE, "TIP"),
        "you": (C.CYAN, "YOU"),
    }

    def __init__(self, kind: str, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelInset")
        colour, tag = self.KINDS.get(kind, self.KINDS["info"])
        row = QHBoxLayout(self)
        row.setContentsMargins(9, 7, 9, 7)
        row.setSpacing(9)

        marker = QLabel("▍")
        marker.setStyleSheet(f"color: {colour};")
        marker.setFont(font(15))
        row.addWidget(marker, alignment=Qt.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(1)
        self.title = QLabel(title)
        self.title.setFont(font(11, 600))
        self.title.setStyleSheet(f"color: {C.TEXT};")
        self.title.setWordWrap(True)
        self.subtitle = QLabel(subtitle)
        self.subtitle.setFont(font(10))
        self.subtitle.setStyleSheet(f"color: {C.TEXT_MUTED};")
        body.addWidget(self.title)
        body.addWidget(self.subtitle)
        row.addLayout(body, stretch=1)

        meta = QVBoxLayout()
        meta.setSpacing(1)
        badge = QLabel(tag)
        badge.setFont(font(9, 700, "mono", spacing=0.6))
        badge.setStyleSheet(f"color: {colour};")
        badge.setAlignment(Qt.AlignRight)
        stamp = QLabel(datetime.now().strftime("%H:%M"))
        stamp.setFont(font(9, 500, "mono"))
        stamp.setStyleSheet(f"color: {C.TEXT_FAINT};")
        stamp.setAlignment(Qt.AlignRight)
        meta.addWidget(badge)
        meta.addWidget(stamp)
        row.addLayout(meta)


class TimelineRow(QWidget):
    """A moment in the session timeline: time, label, elapsed."""

    def __init__(self, when: str, label: str, detail: str, colour: str, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 3, 0, 3)
        row.setSpacing(9)

        time_label = QLabel(when)
        time_label.setFont(font(10, 500, "mono"))
        time_label.setStyleSheet(f"color: {C.TEXT_MUTED};")
        time_label.setFixedWidth(52)
        row.addWidget(time_label)

        dot = StatusDot(colour, pulse=False)
        row.addWidget(dot, alignment=Qt.AlignVCenter)

        text = QLabel(label)
        text.setFont(font(11, 500))
        text.setStyleSheet(
            f"color: {C.TEXT}; border-bottom: 1px solid {rgba(C.CYAN, 0.14)};"
        )
        text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row.addWidget(text, stretch=1)

        elapsed = QLabel(detail)
        elapsed.setFont(font(10, 500, "mono"))
        elapsed.setStyleSheet(f"color: {C.TEXT_FAINT};")
        row.addWidget(elapsed)


class ProviderChip(QFrame):
    """One LLM / integration in the status grid."""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelInset")
        self.setFixedHeight(48)
        row = QHBoxLayout(self)
        row.setContentsMargins(9, 6, 9, 6)
        row.setSpacing(9)

        self.mark = QLabel(name[0].upper())
        self.mark.setFixedSize(26, 26)
        self.mark.setAlignment(Qt.AlignCenter)
        self.mark.setFont(font(12, 700, "display"))
        row.addWidget(self.mark)

        body = QVBoxLayout()
        body.setSpacing(0)
        title = QLabel(name)
        title.setFont(font(11, 600))
        title.setStyleSheet(f"color: {C.TEXT};")
        self.state = QLabel("Not linked")
        self.state.setFont(font(10, 500))
        body.addWidget(title)
        body.addWidget(self.state)
        row.addLayout(body)
        row.addStretch()
        self.set_linked(False)

    def set_linked(self, linked: bool, detail: str | None = None):
        colour = C.GREEN if linked else C.TEXT_FAINT
        self.state.setText(detail or ("Connected" if linked else "Not linked"))
        self.state.setStyleSheet(f"color: {colour};")
        self.mark.setStyleSheet(
            f"background: {rgba(colour, 0.14)}; color: {colour};"
            f"border: 1px solid {rgba(colour, 0.32)}; border-radius: 7px;"
        )


class QuickCommand(QPushButton):
    """A one-tap prompt. Clicking sends its text straight to the assistant."""

    fired = Signal(str)

    def __init__(self, glyph: str, label: str, prompt: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Ghost")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(42)
        self.setFont(font(12, 500))
        self.setText(f"  {glyph}    {label}")
        self._prompt = prompt
        self.clicked.connect(lambda: self.fired.emit(self._prompt))


class StatTile(QWidget):
    """Big number over a small caption, for the memory panel."""

    def __init__(self, caption: str, value: str = "0", parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        self.caption = QLabel(caption)
        self.caption.setFont(font(10, 500))
        self.caption.setStyleSheet(f"color: {C.TEXT_MUTED};")
        self.value = QLabel(value)
        self.value.setFont(font(21, 700, "mono"))
        self.value.setStyleSheet(f"color: {C.TEXT};")
        box.addWidget(self.caption)
        box.addWidget(self.value)

    def set_value(self, value):
        self.value.setText(str(value))


class FooterStat(QFrame):
    """Footer telemetry: glyph, caption, value."""

    def __init__(self, glyph: str, caption: str, value: str, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelInset")
        self.setFixedHeight(48)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 5, 14, 5)
        row.setSpacing(9)
        icon = QLabel(glyph)
        icon.setFont(font(14))
        icon.setStyleSheet(f"color: {C.CYAN};")
        row.addWidget(icon)
        body = QVBoxLayout()
        body.setSpacing(0)
        self.caption = QLabel(caption)
        self.caption.setFont(font(9, 500))
        self.caption.setStyleSheet(f"color: {C.TEXT_FAINT};")
        self.value = QLabel(value)
        self.value.setFont(font(11, 600))
        self.value.setStyleSheet(f"color: {C.TEXT};")
        body.addWidget(self.caption)
        body.addWidget(self.value)
        row.addLayout(body)

    def set_value(self, value: str):
        self.value.setText(value)


def relative_time(stamp: datetime) -> str:
    """'now', '4m', '2h' - compact enough for a timeline column."""
    delta = (datetime.now() - stamp).total_seconds()
    if delta < 45:
        return "now"
    if delta < 3600:
        return f"{int(delta // 60)}m"
    if delta < 86400:
        return f"{int(delta // 3600)}h"
    return f"{int(delta // 86400)}d"
