"""Speech-to-text. Local faster-whisper by default; OpenAI Whisper API optional."""
from __future__ import annotations

import io
import logging
import wave

import numpy as np

log = logging.getLogger(__name__)


def to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio.astype(np.int16).tobytes())
    return buf.getvalue()


class Transcriber:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.engine = cfg["stt"]["engine"]
        self.sample_rate = cfg["audio"]["sample_rate"]
        self._model = None
        if self.engine == "faster-whisper":
            self._load_faster_whisper()

    def _load_faster_whisper(self) -> None:
        from faster_whisper import WhisperModel

        scfg = self.cfg["stt"]
        device = scfg["device"]
        compute = scfg["compute_type"]
        if device == "auto":
            device, compute = _pick_device(compute)
        log.info("loading whisper '%s' on %s (%s)", scfg["model"], device, compute)
        self._model = WhisperModel(scfg["model"], device=device, compute_type=compute)

    def transcribe(self, audio: np.ndarray) -> str:
        if audio is None or len(audio) == 0:
            return ""
        if self.engine == "faster-whisper":
            return self._transcribe_local(audio)
        if self.engine == "whisper-api":
            return self._transcribe_api(audio)
        raise ValueError(f"unknown stt engine: {self.engine}")

    def _transcribe_local(self, audio: np.ndarray) -> str:
        # faster-whisper wants float32 in [-1, 1].
        samples = audio.astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(
            samples,
            language=self.cfg["stt"]["language"],
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    def _transcribe_api(self, audio: np.ndarray) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self.cfg["secrets"]["openai_api_key"])
        wav = to_wav_bytes(audio, self.sample_rate)
        result = client.audio.transcriptions.create(
            model="whisper-1", file=("utterance.wav", wav, "audio/wav")
        )
        return (result.text or "").strip()


def _pick_device(preferred_compute: str) -> tuple[str, str]:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", preferred_compute if preferred_compute != "float16" else "int8"
