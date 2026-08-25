"""The main loop.

    idle -> (wake word) -> listening -> thinking -> speaking -> idle
                              ^                                   |
                              +------- follow-up window ----------+

Runs on a background thread so a GUI can own the main thread. Everything
interesting is published on the Bus for the UI to draw.
"""
from __future__ import annotations

import logging
import random
import threading
import time

from ..audio.mic import MicStream
from ..audio.stt import Transcriber
from ..audio.tts import Speaker
from ..audio.vad import Endpointer
from ..audio.wakeword import WakeWordDetector
from ..brain.agent import Agent
from ..brain.prompts import GREETINGS, acknowledgement
from .state import Bus, State

log = logging.getLogger(__name__)

# Things you can say instead of a request, handled without a model round-trip.
STOP_WORDS = {"stop", "never mind", "nevermind", "cancel", "quiet", "shut up", "that's all", "thats all"}
SLEEP_WORDS = {"go to sleep", "stand down", "goodbye", "that will be all", "dismissed"}


class Assistant:
    def __init__(self, cfg: dict, bus: Bus | None = None):
        self.cfg = cfg
        self.bus = bus or Bus()
        self.state = State.STARTING
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._muted = False

        self.mic: MicStream | None = None
        self.wake: WakeWordDetector | None = None
        self.endpointer: Endpointer | None = None
        self.stt: Transcriber | None = None
        self.speaker: Speaker | None = None
        self.agent: Agent | None = None

    # -- setup -------------------------------------------------------------
    def boot(self) -> None:
        """Load models. Slow (a few seconds), so the HUD shows BOOTING."""
        self._set_state(State.STARTING)
        self._log("Initializing subsystems...")

        self.agent = Agent(self.cfg)
        self._log("Reasoning core online.")

        self.speaker = Speaker(self.cfg)
        self._log(f"Voice: {self.cfg['tts']['engine']}.")

        self.stt = Transcriber(self.cfg)
        self._log(f"Speech recognition: {self.cfg['stt']['model']}.")

        self.endpointer = Endpointer(self.cfg)
        if self.cfg["wake"]["enabled"]:
            self.wake = WakeWordDetector(self.cfg)
            self._log(f"Wake word armed: '{self.cfg['wake']['model'].replace('_', ' ')}'.")

        self.mic = MicStream(self.cfg)
        self.mic.start()
        self._log("Microphone live.")

    # -- lifecycle ---------------------------------------------------------
    def start(self, greet: bool = True) -> None:
        self.boot()
        if greet:
            line = random.choice(GREETINGS).format(
                address=self.cfg["assistant"]["address_user_as"]
            )
            self._speak(line)
        self._thread = threading.Thread(target=self._run, name="jarvis-loop", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self.speaker:
            self.speaker.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        if self.mic:
            self.mic.stop()
        log.info("assistant stopped")

    def _run(self) -> None:
        self._set_state(State.IDLE)
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:
                log.exception("loop error")
                self._set_state(State.ERROR)
                self._log(f"Error: {exc}")
                time.sleep(1.5)
                self._set_state(State.IDLE)

    def _tick(self) -> None:
        """One pass of the idle loop: watch for the wake word."""
        block = self.mic.read(timeout=0.5)
        if block is None:
            return
        self.bus.publish("level", self.mic.level)
        if self._muted or self.wake is None:
            return
        if self.wake.process(block):
            self.handle_turn(preroll=self.mic.preroll())

    # -- a single interaction ---------------------------------------------
    def handle_turn(self, preroll=None, acknowledge: bool = True) -> None:
        """Wake word landed (or the user hit the button). Take it from here."""
        if acknowledge:
            # Short and immediate - it plays while you're still forming the ask.
            self._speak(acknowledgement(self.cfg), blocking=True)
            self.mic.drain()

        while not self._stop.is_set():
            self._set_state(State.LISTENING)
            audio = self.endpointer.record(
                self.mic,
                preroll=preroll,
                on_level=lambda lvl: self.bus.publish("level", lvl),
            )
            preroll = None
            if audio is None or len(audio) == 0:
                self._log("Heard nothing. Standing by.")
                break

            self._set_state(State.THINKING)
            text = self.stt.transcribe(audio)
            if not text or len(text.strip()) < 2:
                self._log("Couldn't make that out.")
                break
            self.bus.publish("transcript", text)
            log.info("user: %s", text)

            normalized = text.strip().lower().rstrip(".!?")
            if normalized in STOP_WORDS:
                self._log("Cancelled.")
                break
            if normalized in SLEEP_WORDS:
                self._speak("Standing by.")
                break

            reply = self.agent.ask(
                text, on_tool=lambda name, args: self.bus.publish("tool", (name, args))
            )
            if reply:
                self.bus.publish("reply", reply)
                log.info("jarvis: %s", reply)
                self._speak(reply)

            # Follow-up window: keep listening briefly so "and also..." works
            # without saying the wake word again.
            if not self._await_followup():
                break

        self._set_state(State.IDLE)

    def _await_followup(self) -> bool:
        """True if the user started speaking again within the window."""
        window = self.cfg["assistant"]["followup_window_sec"]
        if window <= 0:
            return False
        self.mic.drain()
        self._set_state(State.IDLE)
        deadline = time.monotonic() + window
        while time.monotonic() < deadline and not self._stop.is_set():
            block = self.mic.read(timeout=0.2)
            if block is None:
                continue
            self.bus.publish("level", self.mic.level)
            # Any real speech energy in the window means they're still talking.
            if self.mic.level > 0.035:
                self._log("Still listening...")
                return True
        return False

    # -- text mode ---------------------------------------------------------
    def handle_text(self, text: str) -> str:
        """Same brain, typed input. Used by --text mode and the HUD input box."""
        self.bus.publish("transcript", text)
        self._set_state(State.THINKING)
        try:
            reply = self.agent.ask(
                text, on_tool=lambda name, args: self.bus.publish("tool", (name, args))
            )
        finally:
            self._set_state(State.IDLE)
        if reply:
            self.bus.publish("reply", reply)
            self._speak(reply)
        return reply

    # -- helpers -----------------------------------------------------------
    def _speak(self, text: str, blocking: bool = True) -> None:
        if not text:
            return
        previous = self.state
        self._set_state(State.SPEAKING)
        try:
            self.speaker.say(text, blocking=blocking)
        finally:
            # Drop whatever the mic picked up of our own voice, so JARVIS
            # doesn't hear itself and answer its own question.
            if self.mic:
                self.mic.drain()
            if self.wake:
                self.wake.reset()
            self._set_state(previous if previous != State.SPEAKING else State.IDLE)

    def _set_state(self, state: State) -> None:
        if state != self.state:
            self.state = state
            self.bus.publish("state", state)

    def _log(self, message: str) -> None:
        log.info(message)
        self.bus.publish("log", message)

    def toggle_mute(self) -> bool:
        self._muted = not self._muted
        self._log("Microphone muted." if self._muted else "Microphone live.")
        return self._muted

    @property
    def muted(self) -> bool:
        return self._muted
