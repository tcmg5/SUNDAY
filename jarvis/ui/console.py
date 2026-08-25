"""Terminal UI - the fallback when Qt isn't available, and for --text mode."""
from __future__ import annotations

import sys
import threading

from ..core.state import STATE_LABELS, Event, State

ANSI = {
    State.STARTING: "\033[90m",
    State.IDLE: "\033[36m",
    State.LISTENING: "\033[96m",
    State.THINKING: "\033[33m",
    State.SPEAKING: "\033[92m",
    State.ERROR: "\033[91m",
}
RESET = "\033[0m"
DIM = "\033[2m"

BANNER = r"""
    ___  _   ___     _____ ___
   |_  || | | | |   |_   _/ __|
  _  | || |_| | |     | | \__ \    J.A.R.V.I.S.
 | |_| ||  _  | |___  | | |___/    voice interface online
  \___/ |_| |_|_____| |_|
"""


class Console:
    def __init__(self, assistant, cfg: dict):
        self.assistant = assistant
        self.cfg = cfg
        self._lock = threading.Lock()
        assistant.bus.subscribe(self._on_event)

    def _on_event(self, event: Event):
        with self._lock:
            if event.kind == "state":
                color = ANSI.get(event.payload, "")
                sys.stdout.write(f"\r{color}● {STATE_LABELS.get(event.payload, '')}{RESET}      \n")
            elif event.kind == "transcript":
                print(f"\033[96m▸ you:{RESET} {event.payload}")
            elif event.kind == "reply":
                print(f"\033[92m▸ jarvis:{RESET} {event.payload}")
            elif event.kind == "tool":
                name, args = event.payload
                detail = ", ".join(f"{k}={v}" for k, v in list(args.items())[:3])
                print(f"{DIM}  ⟢ {name}({detail}){RESET}")
            elif event.kind == "log":
                print(f"{DIM}  · {event.payload}{RESET}")
            sys.stdout.flush()


def run_console(assistant, cfg: dict) -> int:
    print(f"\033[36m{BANNER}{RESET}")
    Console(assistant, cfg)
    assistant.start()
    print(f'{DIM}Listening for "hey JARVIS". Ctrl-C to shut down.{RESET}\n')
    try:
        while True:
            threading.Event().wait(1.0)
    except KeyboardInterrupt:
        print("\nShutting down.")
        assistant.stop()
    return 0


def run_text_mode(assistant, cfg: dict) -> int:
    """No microphone: type at it. Same brain, same tools, still speaks replies."""
    print(f"\033[36m{BANNER}{RESET}")
    Console(assistant, cfg)
    assistant.boot()
    print(f"{DIM}Text mode. Type a command, or 'exit' to quit.{RESET}\n")
    try:
        while True:
            try:
                text = input("\033[96myou ▸\033[0m ").strip()
            except EOFError:
                break
            if not text:
                continue
            if text.lower() in {"exit", "quit", "q"}:
                break
            assistant.handle_text(text)
    except KeyboardInterrupt:
        pass
    finally:
        assistant.stop()
    print("\nShutting down.")
    return 0
