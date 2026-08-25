#!/usr/bin/env python3
"""Render the command center to docs/command-center.png without a microphone.

Drives a stub assistant through a scripted exchange so the panels have real
content, then grabs the window. Runs headless via Qt's offscreen platform.

    python tools/screenshot.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.config import load_config  # noqa: E402
from jarvis.core.state import Bus, State  # noqa: E402

OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "command-center.png"


class StubMic:
    level = 0.42
    running = True


class StubAssistant:
    """Enough of the Assistant surface for the dashboard to bind to."""

    def __init__(self):
        self.bus = Bus()
        self.mic = StubMic()
        self.state = State.IDLE

    def start(self): pass
    def stop(self): pass
    def toggle_mute(self): return True
    def handle_turn(self, **kwargs): pass
    def handle_text(self, text): pass


SCRIPT = [
    ("log", "Reasoning core online."),
    ("log", "Wake word armed: hey jarvis."),
    ("state", State.LISTENING),
    ("transcript", "organize my downloads folder"),
    ("tool", ("inspect_directory", {"directory": "~/Downloads"})),
    ("tool", ("organize_files", {"directory": "~/Downloads", "dry_run": True})),
    ("reply", "Forty-one files, mostly PDFs and images. Shall I file them by type?"),
    ("transcript", "yes, go ahead"),
    ("tool", ("web_search", {"query": "weather in tokyo"})),
]


def main() -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from jarvis.ui.command_center import CommandCenter

    cfg = load_config()
    # Show the integration panel in a representative state for the docs.
    cfg["secrets"]["anthropic_api_key"] = "sk-ant-****"
    cfg["secrets"]["elevenlabs_api_key"] = "el-****"

    app = QApplication(sys.argv)
    assistant = StubAssistant()
    window = CommandCenter(assistant, cfg)
    window.resize(1680, 980)
    window.show()

    QTimer.singleShot(300, lambda: [assistant.bus.publish(k, v) for k, v in SCRIPT])

    def capture():
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        window.grab().save(str(OUTPUT))
        print(f"wrote {OUTPUT}")
        app.quit()

    # Let the animations settle before grabbing, so the globe isn't mid-frame.
    QTimer.singleShot(2000, capture)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
