"""Assistant state, and the event bus the UI listens on."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class State(str, Enum):
    STARTING = "starting"
    IDLE = "idle"            # armed, waiting for "hey JARVIS"
    LISTENING = "listening"  # recording your request
    THINKING = "thinking"    # model + tools running
    SPEAKING = "speaking"    # reading the answer back
    ERROR = "error"


# What the HUD paints for each state.
STATE_COLORS = {
    State.STARTING: "#666B7A",
    State.IDLE: "#2E7D9A",
    State.LISTENING: "#4FD3FF",
    State.THINKING: "#FFB454",
    State.SPEAKING: "#7CFFB2",
    State.ERROR: "#FF5C5C",
}

STATE_LABELS = {
    State.STARTING: "BOOTING",
    State.IDLE: "STANDBY",
    State.LISTENING: "LISTENING",
    State.THINKING: "PROCESSING",
    State.SPEAKING: "SPEAKING",
    State.ERROR: "FAULT",
}


@dataclass
class Event:
    """Something worth telling the UI about."""
    kind: str          # "state" | "transcript" | "reply" | "tool" | "log" | "level"
    payload: object = None


@dataclass
class Bus:
    """Dead-simple pub/sub. The assistant publishes; the UI subscribes."""
    _subscribers: list[Callable[[Event], None]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def subscribe(self, fn: Callable[[Event], None]) -> None:
        with self._lock:
            self._subscribers.append(fn)

    def publish(self, kind: str, payload: object = None) -> None:
        event = Event(kind, payload)
        with self._lock:
            subscribers = list(self._subscribers)
        for fn in subscribers:
            try:
                fn(event)
            except Exception:
                # A broken UI callback must never take the voice loop down.
                pass
