"""Voice-activity detection and utterance endpointing.

After the wake word fires we answer one question repeatedly: "are they still
talking?" Getting it wrong either cuts people off mid-sentence or leaves the
mic open through the silence afterwards.

Two detectors live here:

  EnergyVAD   The default. Adaptive noise floor plus a zero-crossing check, in
              numpy, with no dependencies. Tuned for the actual job - a desktop
              mic, close range, immediately after a wake word - rather than for
              telephony in general.
  webrtcvad   Used automatically when the package is importable. Google's
              GMM-based detector is more robust in a noisy room, but it ships
              no Windows wheels and its PyInstaller hook breaks on the
              prebuilt-wheel fork, so it is optional rather than required.
"""
from __future__ import annotations

import logging
from collections import deque

import numpy as np

log = logging.getLogger(__name__)

FRAME_MS = 30

# Nothing below this RMS (int16 scale) counts as speech, whatever the noise
# floor has adapted to. Stops a dead-silent room from triggering on its own hiss.
ABSOLUTE_FLOOR = 150.0

# How far above the noise floor a frame must sit, per aggressiveness level.
MARGIN_DB = {0: 5.0, 1: 7.0, 2: 9.5, 3: 12.5}


class EnergyVAD:
    """Adaptive-threshold voice detection using minimum statistics.

    The noise floor is the 10th percentile of the last ~1.5 seconds of frame
    energies, not a value seeded from the first frame. That distinction matters:
    the recorder starts with a pre-roll buffer, so frame one is very often
    already speech, and seeding from it would set the floor at speaking volume
    and detect nothing at all.

    Speech is bursty enough that a 1.5-second window almost always contains a
    quiet gap. When it genuinely doesn't - someone talking continuously - the
    window's quietest frames are inter-word gaps, still well below the peaks.
    """

    # Until the window fills, never assume a floor above this (dB, int16 scale).
    # A real room that is louder than this will raise it within a few frames.
    INITIAL_NOISE_DB = 20.0 * np.log10(ABSOLUTE_FLOOR)
    WINDOW_FRAMES = 50  # ~1.5s at 30ms

    def __init__(self, sample_rate: int = 16000, aggressiveness: int = 2):
        self.sample_rate = sample_rate
        self.margin_db = MARGIN_DB.get(aggressiveness, MARGIN_DB[2])
        self._history: deque[float] = deque(maxlen=self.WINDOW_FRAMES)

    @staticmethod
    def _db(rms: float) -> float:
        return 20.0 * np.log10(max(rms, 1e-6))

    @staticmethod
    def _zero_crossing_rate(frame: np.ndarray) -> float:
        if len(frame) < 2:
            return 0.0
        signs = np.signbit(frame.astype(np.float32))
        return float(np.count_nonzero(signs[1:] != signs[:-1])) / (len(frame) - 1)

    @property
    def noise_db(self) -> float:
        """Current estimate of the room, in dB."""
        if not self._history:
            return self.INITIAL_NOISE_DB
        floor = float(np.percentile(np.fromiter(self._history, dtype=np.float32), 10))
        if len(self._history) < 8:
            # Too little evidence to trust a high floor; stay conservative so
            # speech in the opening frames is still detected.
            return min(floor, self.INITIAL_NOISE_DB)
        return floor

    def is_speech(self, frame: np.ndarray) -> bool:
        samples = frame.astype(np.float32)
        rms = float(np.sqrt(np.mean(samples**2)))
        db = self._db(rms)
        floor = self.noise_db
        # Record before deciding, so the window reflects the room as it is.
        self._history.append(db)

        if rms < ABSOLUTE_FLOOR:
            return False
        if db < floor + self.margin_db:
            return False
        # Voiced speech crosses zero moderately often; a DC thump or low rumble
        # barely does. Very high rates are fricatives, which are still speech.
        return self._zero_crossing_rate(samples) >= 0.01

    def reset(self) -> None:
        self._history.clear()


class _WebRtcVAD:
    """Thin adapter so both detectors present the same is_speech(frame)."""

    def __init__(self, sample_rate: int, aggressiveness: int):
        import webrtcvad

        self.sample_rate = sample_rate
        self._vad = webrtcvad.Vad(aggressiveness)

    def is_speech(self, frame: np.ndarray) -> bool:
        try:
            return bool(self._vad.is_speech(frame.astype(np.int16).tobytes(), self.sample_rate))
        except Exception:
            return False

    def reset(self) -> None:
        pass


def make_detector(sample_rate: int, aggressiveness: int, prefer_webrtc: bool = True):
    """webrtcvad when it's installed, the built-in detector otherwise."""
    if prefer_webrtc:
        try:
            detector = _WebRtcVAD(sample_rate, aggressiveness)
            log.debug("voice detection: webrtcvad")
            return detector
        except Exception as exc:
            log.debug("webrtcvad unavailable (%s); using the built-in detector", exc)
    return EnergyVAD(sample_rate, aggressiveness)


class Endpointer:
    """Streaming utterance recorder with silence-based cutoff."""

    def __init__(self, cfg: dict):
        acfg = cfg["audio"]
        self.sample_rate: int = acfg["sample_rate"]
        self.silence_timeout: float = acfg["silence_timeout_sec"]
        self.max_utterance: float = acfg["max_utterance_sec"]
        self.min_utterance: float = acfg["min_utterance_sec"]
        self.frame_len = int(self.sample_rate * FRAME_MS / 1000)
        self._detector = make_detector(
            self.sample_rate,
            acfg["vad_aggressiveness"],
            prefer_webrtc=acfg.get("prefer_webrtcvad", True),
        )

    def _is_speech(self, frame: np.ndarray) -> bool:
        if len(frame) < self.frame_len:
            return False
        return self._detector.is_speech(frame)

    def record(self, mic, preroll: np.ndarray | None = None, on_level=None) -> np.ndarray:
        """Block until the speaker finishes, then return the utterance as int16.

        `preroll` is prepended (audio captured before we started listening).
        `on_level` is called with 0..1 RMS for UI animation.
        """
        self._detector.reset()
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

            # Re-chunk into exact 30ms frames for the detector.
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
                    # Before speech starts, allow longer - people pause after
                    # the wake word before actually asking for anything.
                    limit = self.silence_timeout if started else 2.5
                    if silence_run >= limit:
                        audio = np.concatenate(collected) if collected else np.zeros(0, np.int16)
                        return audio if started else np.zeros(0, dtype=np.int16)

        audio = np.concatenate(collected) if collected else np.zeros(0, dtype=np.int16)
        if len(audio) / self.sample_rate < self.min_utterance:
            return np.zeros(0, dtype=np.int16)
        return audio
