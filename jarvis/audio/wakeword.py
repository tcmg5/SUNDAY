"""Wake-word detection using openWakeWord's pretrained "hey jarvis" model.

openWakeWord ships a `hey_jarvis` model trained on ~200k synthetic utterances of
the phrase, runs on CPU in ONNX, and needs no API key or account. That is why
this project says "hey JARVIS" and not something else - it's the one wake phrase
with a good free model already trained for it.
"""
from __future__ import annotations

import logging
import time

import numpy as np

log = logging.getLogger(__name__)


class WakeWordDetector:
    def __init__(self, cfg: dict):
        wcfg = cfg["wake"]
        self.threshold: float = wcfg["threshold"]
        self.cooldown: float = wcfg["cooldown_sec"]
        self.model_name: str = wcfg["model"]
        self._last_fire = 0.0
        self._model = None
        self._score = 0.0
        custom = wcfg.get("custom_model_path")

        import openwakeword
        from openwakeword.model import Model

        # First run downloads the ~2MB ONNX models into the package dir.
        try:
            openwakeword.utils.download_models()
        except Exception as exc:  # offline after first run is fine
            log.debug("wake model download skipped: %s", exc)

        models = [custom] if custom else [self.model_name]
        self._model = Model(wakeword_models=models, inference_framework="onnx")
        log.info("wake word armed: '%s' (threshold %.2f)", self.model_name, self.threshold)

    def process(self, block: np.ndarray) -> bool:
        """Feed one 80ms block. True when the wake phrase just landed."""
        if self._model is None:
            return False
        scores = self._model.predict(block)
        self._score = max(scores.values()) if scores else 0.0
        if self._score < self.threshold:
            return False
        now = time.monotonic()
        if now - self._last_fire < self.cooldown:
            return False
        self._last_fire = now
        self.reset()
        log.info("wake word detected (score %.2f)", self._score)
        return True

    def reset(self) -> None:
        """Clear internal buffers so the same utterance can't re-trigger."""
        if self._model is not None:
            try:
                self._model.reset()
            except Exception:
                pass

    @property
    def score(self) -> float:
        return self._score
