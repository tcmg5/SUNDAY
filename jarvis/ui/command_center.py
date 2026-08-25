"""The command center: a full-screen operations dashboard.

Every panel is fed from something real - psutil for the monitor, the tool
dispatcher for agent activity, the event bus for the feed, the config for
provider status. Nothing here invents numbers.
"""
from __future__ import annotations

import logging
import platform
import sys
import threading
from collections import deque
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ..core.state import STATE_COLORS, STATE_LABELS, Event, State
from .panels import (
    GLYPHS, AgentCard, FeedItem, FooterStat, NavItem, ProviderChip, QuickCommand,
    StatTile, SubsystemRow, TimelineRow, relative_time,
)
from .theme import STYLESHEET, C, M, font, rgba
from .widgets import (
    Constellation, DonutGauge, GridBackground, HoloGlobe, MicOrb, Panel,
    Sparkline, StatusDot, WaveBars, glow,
)

log = logging.getLogger(__name__)

# Which agent tile lights up for which tool. This is the whole mapping - an
# "agent" here is a named group of capabilities, not a separate process.
AGENT_GROUPS = {
    "Research": (GLYPHS["search"], C.CYAN, {"web_search", "fetch_page"}),
    "Files": (GLYPHS["tasks"], C.BLUE, {
        "organize_files", "find_files", "inspect_directory", "move_file",
        "delete_file", "create_folder", "undo_last_organize",
    }),
    "Memory": (GLYPHS["memory"], C.PURPLE, {"remember", "recall"}),
    "Browser": (GLYPHS["browser"], C.ORANGE, {
        "open_url", "search_web_in_browser", "open_application",
    }),
    "Coding": (GLYPHS["code"], C.GREEN, {"read_text_file", "run_shell"}),
    "System": (GLYPHS["system"], C.PINK, {
        "get_system_status", "take_screenshot", "clipboard", "set_volume",
    }),
}

QUICK_COMMANDS = [
    (GLYPHS["tasks"], "Tidy my downloads", "organize my downloads folder"),
    (GLYPHS["search"], "Search the web", "search the web for "),
    (GLYPHS["system"], "System report", "give me a full system status report"),
    (GLYPHS["memory"], "What do you remember?", "what have I asked you to remember?"),
    (GLYPHS["clock"], "Undo last change", "undo the last file operation"),
]


class CommandCenter(QWidget):
    _event = Signal(object)

    def __init__(self, assistant, cfg: dict):
        super().__init__()
        self.assistant = assistant
        self.cfg = cfg
        self.state = State.STARTING
        self._drag_offset = None
        self._turns = 0
        self._tool_calls = 0
        self._timeline: deque = deque(maxlen=7)
        self._feed_items: deque = deque(maxlen=9)
        self._agent_cards: dict[str, AgentCard] = {}
        self._subsystems: dict[str, SubsystemRow] = {}

        self._build()
        self._event.connect(self._on_event)
        assistant.bus.subscribe(lambda e: self._event.emit(e))
        self._start_timers()

    # ══ construction ═════════════════════════════════════════════════════
    def _build(self):
        self.setWindowTitle("JARVIS Command Center")
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setStyleSheet(STYLESHEET)
        self.resize(1600, 940)
        self.setMinimumSize(1180, 760)

        self.background = GridBackground(self)
        self.background.lower()

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._sidebar())

        right = QVBoxLayout()
        right.setContentsMargins(M.gap, M.gap, M.gap, M.gap)
        right.setSpacing(M.gap)
        right.addWidget(self._header())
        right.addLayout(self._main_grid(), stretch=1)
        right.addWidget(self._footer())
        outer.addLayout(right, stretch=1)

    # -- sidebar ---------------------------------------------------------
    def _sidebar(self) -> QWidget:
        bar = QFrame()
        bar.setFixedWidth(M.sidebar_width)
        bar.setStyleSheet(
            f"QFrame {{ background: {rgba(C.PANEL, 0.72)};"
            f"border-right: 1px solid {rgba(C.CYAN, 0.16)}; }}"
        )
        box = QVBoxLayout(bar)
        box.setContentsMargins(14, 16, 14, 14)
        box.setSpacing(10)

        # Wordmark
        brand = QHBoxLayout()
        brand.setSpacing(11)
        mark = QLabel("◉")
        mark.setFixedSize(40, 40)
        mark.setAlignment(Qt.AlignCenter)
        mark.setFont(font(19))
        mark.setStyleSheet(
            f"background: {rgba(C.CYAN, 0.12)}; color: {C.CYAN};"
            f"border: 1px solid {rgba(C.CYAN, 0.40)}; border-radius: 10px;"
        )
        glow(mark, C.CYAN, 22, 130)
        brand.addWidget(mark)
        wordmark = QVBoxLayout()
        wordmark.setSpacing(0)
        name = QLabel(self.cfg["assistant"]["name"].upper())
        name.setFont(font(19, 700, "display", spacing=3.4))
        name.setStyleSheet(f"color: {C.TEXT};")
        tag = QLabel("COMMAND CENTER")
        tag.setFont(font(8, 600, "display", spacing=2.2))
        tag.setStyleSheet(f"color: {C.CYAN_DIM};")
        wordmark.addWidget(name)
        wordmark.addWidget(tag)
        brand.addLayout(wordmark)
        brand.addStretch()
        box.addLayout(brand)
        box.addSpacing(8)

        # Navigation. Only Command Center is a real view today; the rest scroll
        # the dashboard to the matching panel rather than pretending to route.
        self._nav_items = []
        self._nav_badges = {}
        for key, glyph, label, target in (
            ("home", "command", "Command Center", None),
            ("core", "core", "AI Core", "core"),
            ("agents", "agents", "Agents", "agents"),
            ("timeline", "tasks", "Mission Timeline", "timeline"),
            ("memory", "memory", "Memory", "memory"),
            ("chat", "chat", "Conversation", "feed"),
            ("tools", "tools", "Tools & Skills", "tools"),
            ("system", "system", "System", "monitor"),
        ):
            item = NavItem(GLYPHS[glyph], label)
            item.clicked.connect(lambda _=False, t=target, i=item: self._navigate(t, i))
            box.addWidget(item)
            self._nav_items.append(item)
            self._nav_badges[key] = item
        self._nav_items[0].setChecked(True)
        box.addStretch()

        # Voice status well
        well = QFrame()
        well.setObjectName("Panel")
        voice = QVBoxLayout(well)
        voice.setContentsMargins(12, 10, 12, 12)
        voice.setSpacing(6)
        heading = QLabel("VOICE STATUS")
        heading.setFont(font(9, 700, "display", spacing=1.6))
        heading.setStyleSheet(f"color: {C.CYAN_DIM};")
        voice.addWidget(heading)

        self.voice_wave = WaveBars(C.CYAN, bars=34)
        self.voice_wave.setFixedHeight(34)
        voice.addWidget(self.voice_wave)

        self.voice_state = QLabel("Booting...")
        self.voice_state.setAlignment(Qt.AlignCenter)
        self.voice_state.setFont(font(11, 500))
        self.voice_state.setStyleSheet(f"color: {C.TEXT_MUTED};")
        voice.addWidget(self.voice_state)

        self.orb = MicOrb()
        self.orb.setFixedHeight(124)
        self.orb.clicked.connect(self._trigger_listen)
        voice.addWidget(self.orb)

        hint = QLabel("Tap to speak")
        hint.setAlignment(Qt.AlignCenter)
        hint.setFont(font(10, 500))
        hint.setStyleSheet(f"color: {C.TEXT_FAINT};")
        voice.addWidget(hint)
        box.addWidget(well)

        self.mute_button = QPushButton(f"  {GLYPHS['bolt']}   Mute microphone")
        self.mute_button.setObjectName("Ghost")
        self.mute_button.setFixedHeight(38)
        self.mute_button.setFont(font(11, 500))
        self.mute_button.setCursor(Qt.PointingHandCursor)
        self.mute_button.clicked.connect(self._toggle_mute)
        box.addWidget(self.mute_button)
        return bar

    # -- header ----------------------------------------------------------
    def _header(self) -> QWidget:
        head = QFrame()
        head.setFixedHeight(M.header_height)
        head.setObjectName("Panel")
        row = QHBoxLayout(head)
        row.setContentsMargins(16, 8, 12, 8)
        row.setSpacing(14)

        # Status chip
        chip = QFrame()
        chip.setObjectName("PanelInset")
        chip_row = QHBoxLayout(chip)
        chip_row.setContentsMargins(12, 6, 14, 6)
        chip_row.setSpacing(8)
        label = QLabel("SYSTEM STATUS")
        label.setFont(font(10, 700, "display", spacing=1.2))
        label.setStyleSheet(f"color: {C.TEXT_MUTED};")
        self.status_dot = StatusDot(C.AMBER)
        self.status_value = QLabel("BOOTING")
        self.status_value.setFont(font(10, 700, "display", spacing=1.2))
        self.status_value.setStyleSheet(f"color: {C.AMBER};")
        chip_row.addWidget(label)
        chip_row.addWidget(self.status_dot)
        chip_row.addWidget(self.status_value)
        row.addWidget(chip)
        row.addStretch()

        # Clock
        clock_box = QVBoxLayout()
        clock_box.setSpacing(0)
        self.date_label = QLabel()
        self.date_label.setAlignment(Qt.AlignCenter)
        self.date_label.setFont(font(11, 500))
        self.date_label.setStyleSheet(f"color: {C.TEXT_MUTED};")
        self.clock_label = QLabel()
        self.clock_label.setAlignment(Qt.AlignCenter)
        self.clock_label.setFont(font(27, 700, "mono", spacing=1.5))
        self.clock_label.setStyleSheet(f"color: {C.CYAN};")
        clock_box.addWidget(self.date_label)
        clock_box.addWidget(self.clock_label)
        row.addLayout(clock_box)
        row.addStretch()

        # Command input - types straight into the assistant
        self.command_input = QLineEdit()
        self.command_input.setObjectName("Search")
        self.command_input.setPlaceholderText("Type a command...")
        self.command_input.setFont(font(12))
        self.command_input.setFixedWidth(300)
        self.command_input.setFixedHeight(38)
        self.command_input.returnPressed.connect(self._submit_command)
        row.addWidget(self.command_input)

        for glyph, tip, handler in (
            ("⤢", "Maximize / restore", self._toggle_maximize),
            ("—", "Minimize", self.showMinimized),
            ("✕", "Shut down", self.close),
        ):
            button = QPushButton(glyph)
            button.setObjectName("IconBtn")
            button.setFixedSize(34, 34)
            button.setToolTip(tip)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(handler)
            row.addWidget(button)
        return head

    # -- main grid -------------------------------------------------------
    def _main_grid(self) -> QHBoxLayout:
        """Three rails. Left is diagnostics, centre is the core, right is feed."""
        rails = QHBoxLayout()
        rails.setSpacing(M.gap)

        left = QVBoxLayout()
        left.setSpacing(M.gap)
        left.addWidget(self._core_panel(), stretch=4)
        left.addWidget(self._monitor_panel(), stretch=3)
        left.addWidget(self._providers_panel(), stretch=3)

        centre = QVBoxLayout()
        centre.setSpacing(M.gap)
        centre.addWidget(self._globe_panel(), stretch=5)
        centre.addWidget(self._agents_panel(), stretch=3)
        centre.addWidget(self._memory_panel(), stretch=2)

        right = QVBoxLayout()
        right.setSpacing(M.gap)
        right.addWidget(self._feed_panel(), stretch=5)
        right.addWidget(self._timeline_panel(), stretch=3)
        right.addWidget(self._quick_panel(), stretch=3)

        rails.addLayout(left, stretch=3)
        rails.addLayout(centre, stretch=5)
        rails.addLayout(right, stretch=3)
        return rails

    def _timeline_panel(self) -> Panel:
        """Mission timeline - what actually happened this session, newest first."""
        panel = Panel("Mission Timeline", "TODAY")
        self._panel_timeline = panel
        holder = QWidget()
        self.timeline_layout = QVBoxLayout(holder)
        self.timeline_layout.setContentsMargins(0, 0, 0, 0)
        self.timeline_layout.setSpacing(2)
        self.timeline_empty = QLabel("No activity yet this session.")
        self.timeline_empty.setFont(font(11))
        self.timeline_empty.setStyleSheet(f"color: {C.TEXT_FAINT};")
        self.timeline_layout.addWidget(self.timeline_empty)
        self.timeline_layout.addStretch()
        panel.body().addWidget(holder)
        return panel

    def _core_panel(self) -> Panel:
        panel = Panel("AI Core Overview")
        self._panel_core = panel
        for key, glyph, name, colour in (
            ("core", GLYPHS["core"], "Reasoning Core", C.CYAN),
            ("voice", GLYPHS["mic"], "Voice I/O", C.GREEN),
            ("wake", GLYPHS["bolt"], "Wake Word", C.PURPLE),
            ("hearing", GLYPHS["search"], "Speech Recognition", C.BLUE),
            ("memory", GLYPHS["memory"], "Memory Store", C.ORANGE),
            ("tools", GLYPHS["tools"], "Tools", C.PINK),
        ):
            row = SubsystemRow(glyph, name, colour)
            self._subsystems[key] = row
            panel.body().addWidget(row)
        return panel

    def _globe_panel(self) -> Panel:
        panel = Panel()
        panel.body().setContentsMargins(0, 0, 0, 0)
        self.globe = HoloGlobe()
        self.globe.set_identity(
            self.cfg["assistant"]["name"].upper(), "AI CORE", "v1.0.0"
        )
        panel.body().addWidget(self.globe)
        return panel

    def _feed_panel(self) -> Panel:
        panel = Panel("Live Intelligence Feed", "LIVE")
        self._panel_feed = panel
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.feed_layout = QVBoxLayout(holder)
        self.feed_layout.setContentsMargins(0, 0, 4, 0)
        self.feed_layout.setSpacing(6)
        self.feed_layout.addStretch()
        scroll.setWidget(holder)
        panel.body().addWidget(scroll)
        return panel

    def _agents_panel(self) -> Panel:
        panel = Panel("Active Agents")
        self._panel_agents = panel
        grid = QGridLayout()
        grid.setSpacing(8)
        for index, (name, (glyph, colour, _tools)) in enumerate(AGENT_GROUPS.items()):
            card = AgentCard(glyph, f"{name} Agent", colour)
            self._agent_cards[name] = card
            grid.addWidget(card, index // 3, index % 3)
        panel.body().addLayout(grid)
        return panel

    def _quick_panel(self) -> Panel:
        panel = Panel("Quick Commands")
        self._panel_tools = panel
        for glyph, label, prompt in QUICK_COMMANDS:
            button = QuickCommand(glyph, label, prompt)
            button.fired.connect(self._run_quick_command)
            panel.body().addWidget(button)
        panel.body().addStretch()
        return panel

    def _monitor_panel(self) -> Panel:
        panel = Panel("System Monitor")
        self._panel_monitor = panel
        row = QHBoxLayout()
        row.setSpacing(6)
        self.gauges = {}
        for key, label in (("cpu", "CPU"), ("ram", "RAM"), ("disk", "Disk")):
            gauge = DonutGauge(label)
            self.gauges[key] = gauge
            row.addWidget(gauge)
        panel.body().addLayout(row)
        self.cpu_history = Sparkline(C.CYAN)
        self.cpu_history.setFixedHeight(24)
        panel.body().addWidget(self.cpu_history)
        return panel

    def _memory_panel(self) -> Panel:
        panel = Panel("Memory & Session")
        self._panel_memory = panel
        row = QHBoxLayout()
        row.setSpacing(10)
        self.constellation = Constellation()
        row.addWidget(self.constellation, stretch=3)
        stats = QVBoxLayout()
        stats.setSpacing(6)
        self.stat_memories = StatTile("Memories")
        self.stat_turns = StatTile("Session turns")
        self.stat_tools = StatTile("Tool calls")
        for tile in (self.stat_memories, self.stat_turns, self.stat_tools):
            stats.addWidget(tile)
        row.addLayout(stats, stretch=2)
        panel.body().addLayout(row)
        return panel

    def _providers_panel(self) -> Panel:
        panel = Panel("Integrations")
        grid = QGridLayout()
        grid.setSpacing(7)
        self.providers = {}
        names = ["Anthropic", "Piper", "Whisper", "ElevenLabs", "Brave", "Tavily"]
        for index, name in enumerate(names):
            chip = ProviderChip(name)
            self.providers[name] = chip
            grid.addWidget(chip, index % 3, index // 3)
        panel.body().addLayout(grid)
        return panel

    # -- footer ----------------------------------------------------------
    def _footer(self) -> QWidget:
        foot = QFrame()
        foot.setFixedHeight(M.footer_height)
        foot.setObjectName("Panel")
        row = QHBoxLayout(foot)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(10)

        self.stat_host = FooterStat("◈", "Host", platform.node()[:22] or "local")
        self.stat_uptime = FooterStat("◔", "Session", "00:00")
        self.stat_model = FooterStat("⬡", "Model", self.cfg["assistant"]["model"])
        for stat in (self.stat_host, self.stat_uptime, self.stat_model):
            row.addWidget(stat)
        row.addStretch()

        # The primary call to action
        talk = QFrame()
        talk.setObjectName("PanelInset")
        talk.setFixedHeight(56)
        talk.setMinimumWidth(420)
        talk.setCursor(Qt.PointingHandCursor)
        talk.mousePressEvent = lambda _event: self._trigger_listen()
        talk.setStyleSheet(
            f"QFrame#PanelInset {{ background: {rgba(C.CYAN, 0.08)};"
            f"border: 1px solid {rgba(C.CYAN, 0.45)}; border-radius: 10px; }}"
        )
        glow(talk, C.CYAN, 30, 120)
        talk_row = QHBoxLayout(talk)
        talk_row.setContentsMargins(16, 6, 16, 6)
        talk_row.setSpacing(12)
        self.footer_wave_left = WaveBars(C.CYAN, bars=16)
        self.footer_wave_left.setFixedWidth(90)
        talk_row.addWidget(self.footer_wave_left)
        talk_text = QVBoxLayout()
        talk_text.setSpacing(0)
        title = QLabel(f"TALK TO {self.cfg['assistant']['name'].upper()}")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(font(13, 700, "display", spacing=2.4))
        title.setStyleSheet(f"color: {C.CYAN_BRIGHT};")
        self.talk_hint = QLabel('Say "hey JARVIS", or tap here')
        self.talk_hint.setAlignment(Qt.AlignCenter)
        self.talk_hint.setFont(font(10, 500))
        self.talk_hint.setStyleSheet(f"color: {C.TEXT_MUTED};")
        talk_text.addWidget(title)
        talk_text.addWidget(self.talk_hint)
        talk_row.addLayout(talk_text, stretch=1)
        self.footer_wave_right = WaveBars(C.CYAN, bars=16)
        self.footer_wave_right.setFixedWidth(90)
        talk_row.addWidget(self.footer_wave_right)
        row.addWidget(talk)
        row.addStretch()

        self.stat_state = FooterStat("⬢", "State", "Booting")
        row.addWidget(self.stat_state)
        return foot

    # ══ live data ════════════════════════════════════════════════════════
    def _start_timers(self):
        self._started_at = datetime.now()

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._tick_clock)
        self.clock_timer.start(1000)
        self._tick_clock()

        self.metrics_timer = QTimer(self)
        self.metrics_timer.timeout.connect(self._tick_metrics)
        self.metrics_timer.start(2000)
        QTimer.singleShot(300, self._tick_metrics)

        self.level_timer = QTimer(self)
        self.level_timer.timeout.connect(self._tick_level)
        self.level_timer.start(60)

        QTimer.singleShot(600, self._refresh_providers)

    def _tick_clock(self):
        now = datetime.now()
        self.date_label.setText(now.strftime("%A, %d %B %Y"))
        self.clock_label.setText(now.strftime("%H:%M:%S"))
        elapsed = int((now - self._started_at).total_seconds())
        self.stat_uptime.set_value(f"{elapsed // 3600:02d}:{elapsed // 60 % 60:02d}")
        if elapsed % 30 == 0 and self._timeline:
            self._render_timeline()

    def _tick_metrics(self):
        try:
            import psutil
        except ImportError:
            return
        if not getattr(self, "_psutil_primed", False):
            # cpu_percent(interval=None) reports 0.0 until it has two samples
            # to compare, so throw the first reading away.
            psutil.cpu_percent(interval=None)
            self._psutil_primed = True
        cpu = psutil.cpu_percent(interval=None)
        self.gauges["cpu"].set_value(cpu)
        self.cpu_history.push(cpu / 100)
        self.gauges["ram"].set_value(psutil.virtual_memory().percent)
        try:
            from pathlib import Path

            self.gauges["disk"].set_value(psutil.disk_usage(str(Path.home())).percent)
        except OSError:
            pass

    def _tick_level(self):
        """Push the live mic level into everything that visualises it."""
        mic = getattr(self.assistant, "mic", None)
        level = mic.level * 6 if mic is not None and mic.running else 0.0
        level = max(0.0, min(1.0, level))
        listening = self.state in (State.LISTENING, State.SPEAKING)
        self.globe.set_level(level if listening else 0.0)
        self.orb.set_level(level)
        for wave in (self.voice_wave, self.footer_wave_left, self.footer_wave_right):
            wave.set_level(level)
            wave.set_active(listening)

    def _refresh_providers(self):
        """Reflect what is actually configured and importable, not a wish list."""
        secrets = self.cfg.get("secrets", {})
        self.providers["Anthropic"].set_linked(
            bool(secrets.get("anthropic_api_key")),
            self.cfg["assistant"]["model"] if secrets.get("anthropic_api_key") else None,
        )
        self.providers["ElevenLabs"].set_linked(bool(secrets.get("elevenlabs_api_key")))
        self.providers["Brave"].set_linked(bool(secrets.get("brave_api_key")))
        self.providers["Tavily"].set_linked(bool(secrets.get("tavily_api_key")))
        engine = self.cfg["tts"]["engine"]
        self.providers["Piper"].set_linked(
            engine == "piper", self.cfg["tts"]["piper_voice"] if engine == "piper" else "Inactive"
        )
        self.providers["Whisper"].set_linked(True, self.cfg["stt"]["model"])

        # Subsystem rows
        self._subsystems["core"].set_status(
            self.cfg["assistant"]["model"],
            C.GREEN if secrets.get("anthropic_api_key") else C.RED,
        )
        self._subsystems["voice"].set_status(engine.capitalize(), C.GREEN)
        self._subsystems["wake"].set_status(
            self.cfg["wake"]["model"].replace("_", " ") if self.cfg["wake"]["enabled"] else "Disabled",
            C.GREEN if self.cfg["wake"]["enabled"] else C.TEXT_FAINT,
        )
        self._subsystems["hearing"].set_status(self.cfg["stt"]["model"], C.GREEN)
        self._refresh_memory_stats()

        from ..brain import tools

        count = len(tools.tool_names())
        self._subsystems["tools"].set_status(f"{count} available", C.GREEN)
        self._nav_badges["tools"].set_badge(str(count))

    def _refresh_memory_stats(self):
        count = 0
        try:
            from ..brain.tools.system import _load_memory

            count = len(_load_memory())
        except Exception:
            pass
        self.stat_memories.set_value(count)
        self.stat_turns.set_value(self._turns)
        self._nav_badges["chat"].set_badge(str(self._turns) if self._turns else "")
        self._nav_badges["memory"].set_badge(str(count) if count else "")
        self.stat_tools.set_value(self._tool_calls)
        self.constellation.set_count(count)
        self._subsystems["memory"].set_status(f"{count} stored", C.GREEN if count else C.TEXT_MUTED)

    # ══ events ═══════════════════════════════════════════════════════════
    def _on_event(self, event: Event):
        if event.kind == "state":
            self._apply_state(event.payload)
        elif event.kind == "transcript":
            self._turns += 1
            self._add_feed("you", str(event.payload), "Transcribed")
            self._add_timeline(str(event.payload)[:44], C.CYAN)
            self._refresh_memory_stats()
        elif event.kind == "reply":
            self._add_feed("live", str(event.payload), self.cfg["assistant"]["name"])
        elif event.kind == "tool":
            name, args = event.payload
            self._tool_calls += 1
            self._flash_agent(name)
            detail = ", ".join(f"{k}={v}" for k, v in list(args.items())[:2])[:60]
            self._add_feed("info", name.replace("_", " ").title(), detail or "executed")
            self._refresh_memory_stats()
        elif event.kind == "log":
            self._add_feed("tip", str(event.payload), "System")

    def _apply_state(self, state: State):
        self.state = state
        colour = STATE_COLORS.get(state, C.CYAN)
        label = STATE_LABELS.get(state, str(state))

        self.status_value.setText(label)
        self.status_value.setStyleSheet(f"color: {colour};")
        self.status_dot.set_colour(colour, pulse=state != State.ERROR)
        self.voice_state.setText(label.title())
        self.voice_state.setStyleSheet(f"color: {colour};")
        self.stat_state.set_value(label.title())
        self.orb.set_accent(colour)
        for wave in (self.voice_wave, self.footer_wave_left, self.footer_wave_right):
            wave.set_colour(colour)

        speeds = {
            State.IDLE: 0.004, State.LISTENING: 0.016,
            State.THINKING: 0.03, State.SPEAKING: 0.011,
        }
        self.globe.set_accent(colour, speeds.get(state, 0.006))

        hints = {
            State.IDLE: 'Say "hey JARVIS", or tap here',
            State.LISTENING: "Listening...",
            State.THINKING: "Processing...",
            State.SPEAKING: "Speaking...",
            State.STARTING: "Bringing systems online...",
            State.ERROR: "Fault - check the feed",
        }
        self.talk_hint.setText(hints.get(state, ""))
        if state == State.IDLE:
            for card in self._agent_cards.values():
                card.set_active(False)

    def _flash_agent(self, tool_name: str):
        for name, (_glyph, _colour, tool_set) in AGENT_GROUPS.items():
            if tool_name in tool_set:
                card = self._agent_cards[name]
                card.set_active(True, "Working")
                QTimer.singleShot(4000, lambda c=card: c.set_active(False))
                return

    def _add_feed(self, kind: str, title: str, subtitle: str):
        item = FeedItem(kind, title if len(title) < 120 else title[:117] + "...", subtitle)
        self.feed_layout.insertWidget(0, item)
        self._feed_items.appendleft(item)
        # deque eviction returns nothing, so prune the layout by index instead.
        while self.feed_layout.count() > self._feed_items.maxlen + 1:
            widget = self.feed_layout.takeAt(self.feed_layout.count() - 2)
            if widget and widget.widget():
                widget.widget().deleteLater()

    def _add_timeline(self, label: str, colour: str):
        self._timeline.appendleft((datetime.now(), label, colour))
        self._render_timeline()

    def _render_timeline(self):
        """Rebuild the list - it is at most seven rows, so this is cheap."""
        while self.timeline_layout.count():
            item = self.timeline_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._timeline:
            self.timeline_layout.addWidget(self.timeline_empty)
            self.timeline_layout.addStretch()
            return
        for stamp, label, colour in self._timeline:
            self.timeline_layout.addWidget(
                TimelineRow(stamp.strftime("%H:%M"), label, relative_time(stamp), colour)
            )
        self.timeline_layout.addStretch()

    # ══ interaction ══════════════════════════════════════════════════════
    def _navigate(self, target: str | None, item: NavItem):
        for other in self._nav_items:
            other.setChecked(other is item)
        panels = {
            "core": getattr(self, "_panel_core", None),
            "agents": getattr(self, "_panel_agents", None),
            "feed": getattr(self, "_panel_feed", None),
            "memory": getattr(self, "_panel_memory", None),
            "monitor": getattr(self, "_panel_monitor", None),
            "tools": getattr(self, "_panel_tools", None),
            "timeline": getattr(self, "_panel_timeline", None),
        }
        panel = panels.get(target or "")
        if panel is not None:
            # No routing to fake pages - draw attention to the real panel instead.
            panel.setStyleSheet(
                f"QFrame#Panel {{ background: {rgba(C.PANEL, 0.88)};"
                f"border: 1px solid {rgba(C.CYAN, 0.65)}; border-radius: {M.panel_radius}px; }}"
            )
            QTimer.singleShot(900, lambda p=panel: p.setStyleSheet(""))

    def _trigger_listen(self):
        if self.state not in (State.IDLE, State.ERROR):
            return
        threading.Thread(
            target=lambda: self.assistant.handle_turn(acknowledge=True), daemon=True
        ).start()

    def _submit_command(self):
        text = self.command_input.text().strip()
        if not text:
            return
        self.command_input.clear()
        threading.Thread(target=self.assistant.handle_text, args=(text,), daemon=True).start()

    def _run_quick_command(self, prompt: str):
        # Prompts ending in a space are templates - let the operator finish them.
        if prompt.endswith(" "):
            self.command_input.setText(prompt)
            self.command_input.setFocus()
            return
        threading.Thread(target=self.assistant.handle_text, args=(prompt,), daemon=True).start()

    def _toggle_mute(self):
        muted = self.assistant.toggle_mute()
        self.mute_button.setText(
            f"  {GLYPHS['bolt']}   {'Microphone muted' if muted else 'Mute microphone'}"
        )

    def _toggle_maximize(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    # ══ window chrome ════════════════════════════════════════════════════
    def resizeEvent(self, event):  # noqa: N802
        self.background.setGeometry(0, 0, self.width(), self.height())
        super().resizeEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and event.position().y() < M.header_height + M.gap:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_offset is not None and not self.isMaximized():
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag_offset = None

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.position().y() < M.header_height + M.gap:
            self._toggle_maximize()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() == Qt.Key_Space and not self.command_input.hasFocus():
            self._trigger_listen()

    def closeEvent(self, event):  # noqa: N802
        self.assistant.stop()
        event.accept()


def run_command_center(assistant, cfg: dict) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    window = CommandCenter(assistant, cfg)
    window.showMaximized() if cfg["ui"].get("start_maximized", True) else window.show()

    def boot():
        threading.Thread(target=assistant.start, daemon=True).start()

    QTimer.singleShot(200, boot)
    return app.exec()
