"""Voice-activity detection and utterance endpointing.

After the wake word fires we need to answer one question repeatedly: "are they
still talking?" webrtcvad answers it per 30ms frame; this wraps that in the
hysteresis you actually want - wait for speech to *start*, then cut when silence
runs longer than the timeout.
"""
from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)

FRAME_MS = 30


class Endpointer:
    """Streaming utterance recorder with silence-based cutoff."""

    def __init__(self, cfg: dict):
        acfg = cfg["audio"]
        self.sample_rate: int = acfg["sample_rate"]
        self.silence_timeout: float = acfg["silence_timeout_sec"]
        self.max_utterance: float = acfg["max_utterance_sec"]
        self.min_utterance: float = acfg["min_utterance_sec"]
        self.frame_len = int(self.sample_rate * FRAME_MS / 1000)
        self._vad = None
        try:
            import webrtcvad

            self._vad = webrtcvad.Vad(acfg["vad_aggressiveness"])
        except Exception as exc:
            log.warning("webrtcvad unavailable (%s); falling back to RMS gate", exc)
        # Energy fallback threshold, in int16 RMS units.
        self._rms_threshold = 450.0

    def _is_speech(self, frame: np.ndarray) -> bool:
        if len(frame) < self.frame_len:
            return False
        if self._vad is not None:
            try:
                return self._vad.is_speech(frame.tobytes(), self.sample_rate)
            except Exception:
                pass
        return float(np.sqrt(np.mean(frame.astype(np.float32) ** 2))) > self._rms_threshold

    def record(self, mic, preroll: np.ndarray | None = None, on_level=None) -> np.ndarray:
        """Block until the speaker finishes, then return the utterance as int16.

        `preroll` is prepended (the tail of audio captured before we started
        listening). `on_level` is called with 0..1 RMS for UI animation.
        """
        collected: list[np.ndarray] = []
        if preroll is not None and len(preroll):
            collected.append(preroll)

        pending = np.zeros(0, dtype=np.int16)
        silence_run = 0.0
        speech_run = 0.0
        elapsed = 0.0
        started = False

        while elapsed < self.max_utterance:
            block = mic.read(timeout=1.0)
            if block is None:
                break
            collected.append(block)
            elapsed += len(block) / self.sample_rate
            if on_level is not None:
                rms = float(np.sqrt(np.mean(block.astype(np.float32) ** 2))) / 32768.0
                on_level(min(1.0, rms * 6))

            # Re-chunk into exact 30ms frames for the VAD.
            pending = np.concatenate([pending, block])
            while len(pending) >= self.frame_len:
                frame, pending = pending[: self.frame_len], pending[self.frame_len :]
                if self._is_speech(frame):
                    speech_run += FRAME_MS / 1000
                    silence_run = 0.0
                    if speech_run > 0.09:
                        started = True
                else:
                    silence_run += FRAME_MS / 1000
                    # Before speech starts, allow a longer grace period - people
                    # pause after the wake word before actually asking.
                    limit = self.silence_timeout if started else 2.5
                    if silence_run >= limit:
                        audio = np.concatenate(collected) if collected else np.zeros(0, np.int16)
                        return audio if started else np.zeros(0, dtype=np.int16)

        audio = np.concatenate(collected) if collected else np.zeros(0, dtype=np.int16)
        if len(audio) / self.sample_rate < self.min_utterance:
            return np.zeros(0, dtype=np.int16)
        return audio
