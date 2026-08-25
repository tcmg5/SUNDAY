"""Microphone capture: one always-on stream, fanned out to consumers.

The wake-word detector and the utterance recorder both need the same audio, and
opening the device twice fights with the OS. So we open it once and push frames
into a queue plus a short rolling pre-roll buffer. The pre-roll matters: by the
time "hey jarvis" fires, you've often already started the next word, and we want
those samples back.
"""
from __future__ import annotations

import logging
import queue
import threading
from collections import deque

import numpy as np

log = logging.getLogger(__name__)


class MicStream:
    def __init__(self, cfg: dict):
        acfg = cfg["audio"]
        self.sample_rate: int = acfg["sample_rate"]
        self.block_size: int = acfg["block_size"]
        self.channels: int = acfg["channels"]
        self.device = acfg["input_device"]
        # ~1.5s of pre-roll, so we can recover speech that overlaps the wake word.
        preroll_blocks = max(1, int(1.5 * self.sample_rate / self.block_size))
        self._preroll: deque[np.ndarray] = deque(maxlen=preroll_blocks)
        self._q: queue.Queue[np.ndarray] = queue.Queue(maxsize=64)
        self._stream = None
        self._lock = threading.Lock()
        self._level = 0.0
        self._running = False

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        import sounddevice as sd

        def callback(indata, frames, time_info, status):  # noqa: ARG001
            if status:
                log.debug("audio status: %s", status)
            block = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
            with self._lock:
                self._preroll.append(block)
                # RMS in 0..1, used to drive the HUD ring animation.
                self._level = float(np.sqrt(np.mean(block.astype(np.float32) ** 2)) / 32768.0)
            try:
                self._q.put_nowait(block)
            except queue.Full:
                # Dropping a frame beats blocking the audio thread.
                try:
                    self._q.get_nowait()
                    self._q.put_nowait(block)
                except queue.Empty:
                    pass

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            channels=self.channels,
            dtype="int16",
            device=self.device,
            callback=callback,
        )
        self._stream.start()
        self._running = True
        log.info("microphone open @ %d Hz (device=%s)", self.sample_rate, self.device or "default")

    def stop(self) -> None:
        self._running = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    # -- consumption -------------------------------------------------------
    def read(self, timeout: float = 1.0) -> np.ndarray | None:
        """Next block of int16 samples, or None if the mic went quiet on us."""
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> None:
        """Throw away buffered audio (e.g. what we picked up of our own voice)."""
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                return

    def preroll(self) -> np.ndarray:
        with self._lock:
            if not self._preroll:
                return np.zeros(0, dtype=np.int16)
            return np.concatenate(list(self._preroll))

    @property
    def level(self) -> float:
        with self._lock:
            return self._level

    @property
    def running(self) -> bool:
        return self._running


def list_devices() -> str:
    """Human-readable device table, for `python -m jarvis devices`."""
    try:
        import sounddevice as sd
    except Exception as exc:  # pragma: no cover
        return f"sounddevice unavailable: {exc}"
    lines = []
    for idx, dev in enumerate(sd.query_devices()):
        kind = []
        if dev["max_input_channels"] > 0:
            kind.append("in")
        if dev["max_output_channels"] > 0:
            kind.append("out")
        lines.append(f"  [{idx:>2}] {dev['name']}  ({'/'.join(kind)}, {int(dev['default_samplerate'])} Hz)")
    return "\n".join(lines)
