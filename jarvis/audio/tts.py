"""Text-to-speech - "the voice".

Three engines, picked in config:

  piper       Local, free, offline, ~50ms latency on CPU. Default voice is
              en_GB-alan-medium: a measured British male read that is the
              closest freely-available match to Paul Bettany's delivery.
              Downloaded on first use from the rhasspy/piper-voices repo.
  elevenlabs  Best quality by a wide margin, needs an API key and is metered.
              Point `elevenlabs_voice_id` at a JARVIS-style voice.
  system      Whatever the OS ships (macOS `say` / Windows SAPI / espeak-ng).
              Always works, sounds like 2004.

On top of any engine, `jarvis_filter` applies the finishing touch: a high-pass
to strip chestiness and a short reverb tail so it sounds like it is coming from
the room rather than from a podcast mic. That processing is most of the
difference between "a British TTS voice" and "JARVIS".
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np

from ..config import MODELS_DIR

log = logging.getLogger(__name__)

PIPER_VOICES_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

# Voices worth trying for a JARVIS read, best first. See README "The Voice".
RECOMMENDED_PIPER_VOICES = [
    ("en_GB-alan-medium", "British male, calm and measured - closest free match"),
    ("en_GB-northern_english_male-medium", "Warmer, slightly more casual"),
    ("en_GB-semaine-medium", "Clipped and formal, more android than butler"),
    ("en_US-ryan-high", "American, very clean - if you don't want the accent"),
]


class Speaker:
    """Synthesises and plays speech. Blocking by default; call stop() to cut it off."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        tcfg = cfg["tts"]
        self.engine = tcfg["engine"]
        self.volume = float(tcfg["volume"])
        self.output_device = cfg["audio"]["output_device"]
        self._voice = None
        self._stop_flag = threading.Event()
        self._speaking = threading.Event()
        if self.engine == "piper":
            self._load_piper()

    # -- engines -----------------------------------------------------------
    def _load_piper(self) -> None:
        voice_id = self.cfg["tts"]["piper_voice"]
        model_path = ensure_piper_voice(voice_id)
        try:
            from piper import PiperVoice

            self._voice = PiperVoice.load(str(model_path))
            log.info("piper voice loaded: %s", voice_id)
        except ImportError:
            # Fall back to the standalone piper binary if the python package
            # isn't installed but the CLI is.
            if shutil.which("piper"):
                self._voice = ("cli", str(model_path))
                log.info("piper CLI voice: %s", voice_id)
            else:
                log.error("piper not installed; falling back to system TTS")
                self.engine = "system"

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """Text -> (float32 mono samples in [-1,1], sample_rate)."""
        if self.engine == "piper":
            return self._synth_piper(text)
        if self.engine == "elevenlabs":
            return self._synth_elevenlabs(text)
        raise ValueError(f"engine {self.engine} does not synthesize to buffers")

    def _synth_piper(self, text: str) -> tuple[np.ndarray, int]:
        if isinstance(self._voice, tuple):  # CLI mode
            model = self._voice[1]
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                out = tmp.name
            try:
                subprocess.run(
                    ["piper", "--model", model, "--output_file", out],
                    input=text.encode("utf-8"), check=True, capture_output=True,
                )
                return read_wav(out)
            finally:
                os.unlink(out)

        chunks: list[np.ndarray] = []
        rate = 22050
        for chunk in self._voice.synthesize(text):
            # piper >=1.3 yields AudioChunk objects; older yields raw bytes.
            if hasattr(chunk, "audio_int16_array"):
                chunks.append(np.asarray(chunk.audio_int16_array, dtype=np.int16))
                rate = chunk.sample_rate
            elif hasattr(chunk, "audio_int16_bytes"):
                chunks.append(np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16))
                rate = chunk.sample_rate
            else:
                chunks.append(np.frombuffer(chunk, dtype=np.int16))
                rate = getattr(self._voice.config, "sample_rate", 22050)
        if not chunks:
            return np.zeros(0, dtype=np.float32), rate
        return np.concatenate(chunks).astype(np.float32) / 32768.0, rate

    def _synth_elevenlabs(self, text: str) -> tuple[np.ndarray, int]:
        import httpx

        key = self.cfg["secrets"]["elevenlabs_api_key"]
        if not key:
            raise RuntimeError("ELEVENLABS_API_KEY is not set")
        voice_id = self.cfg["tts"]["elevenlabs_voice_id"]
        if not voice_id:
            raise RuntimeError("tts.elevenlabs_voice_id is not set in config.yaml")
        resp = httpx.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={"xi-api-key": key, "accept": "audio/mpeg"},
            json={
                "text": text,
                "model_id": self.cfg["tts"]["elevenlabs_model"],
                "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.15},
            },
            timeout=30,
        )
        resp.raise_for_status()
        return decode_mp3(resp.content)

    # -- playback ----------------------------------------------------------
    def say(self, text: str, blocking: bool = True) -> None:
        text = (text or "").strip()
        if not text or self.engine == "none":
            return
        self._stop_flag.clear()
        if self.engine == "system":
            self._say_system(text, blocking)
            return
        try:
            samples, rate = self.synthesize(text)
        except Exception as exc:
            log.error("tts synthesis failed (%s); using system voice", exc)
            self._say_system(text, blocking)
            return
        if len(samples) == 0:
            return
        if self.cfg["tts"]["jarvis_filter"]:
            samples = apply_jarvis_filter(
                samples, rate,
                reverb=self.cfg["tts"]["filter_reverb"],
                highpass_hz=self.cfg["tts"]["filter_highpass_hz"],
            )
        self._play(samples * self.volume, rate, blocking)

    def _play(self, samples: np.ndarray, rate: int, blocking: bool) -> None:
        import sounddevice as sd

        def run():
            self._speaking.set()
            try:
                sd.play(samples, rate, device=self.output_device)
                while True:
                    stream = sd.get_stream()
                    if stream is None or not stream.active:
                        break
                    if self._stop_flag.is_set():
                        sd.stop()
                        break
                    sd.sleep(50)
            except Exception as exc:
                log.error("playback failed: %s", exc)
            finally:
                self._speaking.clear()

        if blocking:
            run()
        else:
            threading.Thread(target=run, daemon=True).start()

    def _say_system(self, text: str, blocking: bool) -> None:
        system = platform.system()
        if system == "Darwin":
            # Daniel is macOS's British male voice - the nearest built-in.
            cmd = ["say", "-v", "Daniel", text]
        elif system == "Windows":
            script = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "$s.SelectVoiceByHints('Male'); "
                "$s.Speak([Console]::In.ReadToEnd())"
            )
            proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", script],
                stdin=subprocess.PIPE, text=True,
            )
            if blocking:
                proc.communicate(text)
            else:
                # Write and close stdin regardless - PowerShell's ReadToEnd
                # blocks forever on a pipe that never closes.
                proc.stdin.write(text)
                proc.stdin.close()
            return
        elif shutil.which("espeak-ng"):
            cmd = ["espeak-ng", "-v", "en-gb-x-rp", "-s", "150", text]
        elif shutil.which("spd-say"):
            cmd = ["spd-say", text]
        else:
            log.warning("no system TTS available; text only: %s", text)
            return
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if blocking:
            proc.wait()

    def stop(self) -> None:
        self._stop_flag.set()

    @property
    def speaking(self) -> bool:
        return self._speaking.is_set()


# -- the JARVIS finishing filter ------------------------------------------
def one_pole_highpass(x: np.ndarray, rate: int, cutoff_hz: float) -> np.ndarray:
    """Single-pole high-pass: y[n] = a * (y[n-1] + x[n] - x[n-1]).

    -3 dB at the cutoff, 6 dB/octave below it. Gentle on purpose - a steep
    filter makes speech sound thin and telephone-y rather than present.

    The per-sample loop is deliberate: utterances are a few seconds, and this
    costs far less than the synthesis that produced them.
    """
    if cutoff_hz <= 0 or len(x) == 0:
        return x
    a = 1.0 / (1.0 + 2.0 * np.pi * cutoff_hz / rate)
    y = np.empty_like(x)
    prev_x = prev_y = 0.0
    for i in range(len(x)):
        prev_y = a * (prev_y + x[i] - prev_x)
        prev_x = x[i]
        y[i] = prev_y
    return y


def presence_tilt(x: np.ndarray, amount: float = 0.12) -> np.ndarray:
    """Lift the high end slightly. Differentiation is a +6 dB/octave shelf."""
    if len(x) < 2:
        return x
    return x + amount * np.diff(x, prepend=x[0])


# Delay taps in ms with their gains. Non-harmonic spacing avoids the metallic
# ring you get when the taps line up into a comb filter.
REVERB_TAPS = ((23, 0.60), (41, 0.42), (67, 0.30), (97, 0.20), (131, 0.12))


def multitap_reverb(x: np.ndarray, rate: int, amount: float) -> np.ndarray:
    """A short, cheap room. Enough tail to place the voice in a space."""
    if amount <= 0 or len(x) == 0:
        return x
    out = x.copy()
    for delay_ms, gain in REVERB_TAPS:
        d = int(rate * delay_ms / 1000)
        if d >= len(x):
            continue
        out[d:] += x[:-d] * gain * amount
    return out


def apply_jarvis_filter(
    samples: np.ndarray, rate: int, reverb: float = 0.18, highpass_hz: int = 120
) -> np.ndarray:
    """Make clean TTS sound like it is being spoken into a room.

    High-pass to strip the boxy low end that gives TTS away, a presence tilt so
    it carries across a room, and a short reverb tail. Peak-normalised at the
    end so every utterance plays back at a consistent level.
    """
    if len(samples) == 0:
        return samples
    x = samples.astype(np.float32)
    x = one_pole_highpass(x, rate, highpass_hz)
    x = presence_tilt(x)
    x = multitap_reverb(x, rate, reverb)
    peak = float(np.max(np.abs(x))) or 1.0
    return (x / peak * 0.92).astype(np.float32)


# -- voice assets ----------------------------------------------------------
def parse_voice_id(voice_id: str) -> tuple[str, str, str, str]:
    """'en_GB-alan-medium' -> ('en', 'en_GB', 'alan', 'medium')"""
    lang, name, quality = voice_id.split("-", 2)
    return lang.split("_")[0], lang, name, quality


def ensure_piper_voice(voice_id: str) -> Path:
    """Return a local path to the voice model, downloading it if needed."""
    voices_dir = MODELS_DIR / "piper"
    voices_dir.mkdir(parents=True, exist_ok=True)
    model_path = voices_dir / f"{voice_id}.onnx"
    config_path = voices_dir / f"{voice_id}.onnx.json"
    if model_path.exists() and config_path.exists():
        return model_path

    import httpx

    family, lang, name, quality = parse_voice_id(voice_id)
    base = f"{PIPER_VOICES_BASE}/{family}/{lang}/{name}/{quality}/{voice_id}.onnx"
    for url, dest in ((base, model_path), (base + ".json", config_path)):
        log.info("downloading voice asset: %s", url.rsplit("/", 1)[-1])
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)
    log.info("voice ready: %s", voice_id)
    return model_path


def read_wav(path: str) -> tuple[np.ndarray, int]:
    with wave.open(path, "rb") as wf:
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0, rate


def decode_mp3(data: bytes) -> tuple[np.ndarray, int]:
    """MP3 -> samples. Uses miniaudio if present, else shells out to ffmpeg."""
    try:
        import miniaudio

        decoded = miniaudio.decode(data, nchannels=1, sample_rate=22050)
        return np.asarray(decoded.samples, dtype=np.float32) / 32768.0, decoded.sample_rate
    except ImportError:
        pass
    if not shutil.which("ffmpeg"):
        raise RuntimeError("install miniaudio or ffmpeg to play ElevenLabs audio")
    proc = subprocess.run(
        ["ffmpeg", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", "22050", "pipe:1"],
        input=data, capture_output=True, check=True,
    )
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0, 22050
