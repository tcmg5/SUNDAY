"""Configuration loading and defaults for JARVIS.

Config resolution order (later wins):
  1. Built-in DEFAULTS below
  2. config.yaml in the project root (copy config.example.yaml)
  3. Environment variables (JARVIS_*, ANTHROPIC_API_KEY, ELEVENLABS_API_KEY)
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - yaml is a hard dep, but fail readably
    yaml = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MODELS_DIR = PROJECT_ROOT / "models"
LOGS_DIR = PROJECT_ROOT / "logs"

DEFAULTS: dict[str, Any] = {
    "assistant": {
        "name": "JARVIS",
        # How JARVIS addresses you. "sir" is canon; change to your name.
        "address_user_as": "sir",
        # Claude model that does the thinking and tool calling.
        "model": "claude-opus-5",
        "max_tokens": 2048,
        # Turns of conversation kept in context before the oldest are dropped.
        "history_turns": 12,
        # Seconds to keep listening for a follow-up after answering, so you can
        # say "and also..." without repeating the wake word.
        "followup_window_sec": 8.0,
    },
    "wake": {
        "enabled": True,
        # openWakeWord ships a pretrained "hey jarvis" model - no key, offline.
        "model": "hey_jarvis",
        "threshold": 0.5,
        # Seconds to ignore further detections after a trigger (stops doubles).
        "cooldown_sec": 2.0,
        # Path to a custom .onnx wake model; None = use the bundled one.
        "custom_model_path": None,
    },
    "audio": {
        "sample_rate": 16000,
        "channels": 1,
        # 80ms frames - what openWakeWord expects (1280 samples @ 16kHz).
        "block_size": 1280,
        "input_device": None,   # None = system default; int index or name substring
        "output_device": None,
        # Endpointing: stop recording after this much trailing silence.
        "silence_timeout_sec": 1.1,
        # Hard cap on a single utterance.
        "max_utterance_sec": 20.0,
        # Don't bother transcribing anything shorter than this.
        "min_utterance_sec": 0.4,
        "vad_aggressiveness": 2,  # 0-3, higher = more aggressive filtering
    },
    "stt": {
        # "faster-whisper" (local, recommended) | "whisper-api" (needs OpenAI key)
        "engine": "faster-whisper",
        "model": "base.en",     # tiny.en | base.en | small.en | medium.en | large-v3
        "device": "auto",       # auto | cpu | cuda
        "compute_type": "int8", # int8 on CPU, float16 on GPU
        "language": "en",
    },
    "tts": {
        # "piper" (local, free, recommended) | "elevenlabs" (best quality, paid)
        # | "system" (OS built-in) | "none"
        "engine": "piper",
        # Closest free JARVIS-alike: measured British male. See README "The Voice".
        "piper_voice": "en_GB-alan-medium",
        "piper_speed": 1.0,
        "elevenlabs_voice_id": "",
        "elevenlabs_model": "eleven_turbo_v2_5",
        # Subtle post-processing so it reads as "speaking through the room"
        # rather than a podcast mic. See audio/tts.py:apply_jarvis_filter.
        "jarvis_filter": True,
        "filter_reverb": 0.18,   # 0 = dry, 0.5 = cathedral
        "filter_highpass_hz": 120,
        "volume": 1.0,
    },
    "files": {
        # JARVIS may only touch paths under these roots. Nothing else. Ever.
        "safe_roots": ["~/Desktop", "~/Downloads", "~/Documents", "~/Pictures"],
        # Ask before applying a file plan that touches more than this many files.
        "confirm_threshold": 25,
        # Deletions go to the OS trash, never unlink().
        "use_trash": True,
        # Every applied move is journaled so "undo that" works.
        "journal_path": str(DATA_DIR / "file_journal.jsonl"),
    },
    "web": {
        # "duckduckgo" (no key) | "brave" (needs BRAVE_API_KEY) | "tavily"
        "engine": "duckduckgo",
        "max_results": 6,
        "fetch_timeout_sec": 15,
        "max_page_chars": 6000,
    },
    "shell": {
        # Shell access is off by default. Turn it on only if you want it.
        "enabled": False,
        # These run without asking. Anything else prompts for confirmation.
        "allowlist": ["ls", "pwd", "df", "du", "date", "whoami", "uptime"],
        "timeout_sec": 30,
    },
    "ui": {
        # "hud" (floating always-on-top overlay) | "console" | "none"
        "mode": "hud",
        "always_on_top": True,
        "opacity": 0.92,
        "accent": "#4FD3FF",
        "position": "bottom-right",  # or "top-right" | "center" | "bottom-left"
        "click_through_when_idle": False,
    },
    "logging": {
        "level": "INFO",
        "file": str(LOGS_DIR / "jarvis.log"),
        # Save every transcript line to logs/transcript.jsonl
        "save_transcripts": True,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _apply_env(cfg: dict) -> dict:
    """Environment overrides. Keys are secrets or quick one-off toggles."""
    cfg["secrets"] = {
        "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
        "elevenlabs_api_key": os.environ.get("ELEVENLABS_API_KEY", ""),
        "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
        "brave_api_key": os.environ.get("BRAVE_API_KEY", ""),
        "tavily_api_key": os.environ.get("TAVILY_API_KEY", ""),
    }
    # JARVIS_TTS_ENGINE=none -> cfg["tts"]["engine"] = "none"
    for env_key, value in os.environ.items():
        if not env_key.startswith("JARVIS_") or env_key == "JARVIS_CONFIG":
            continue
        parts = env_key[len("JARVIS_"):].lower().split("_", 1)
        if len(parts) != 2:
            continue
        section, key = parts
        if section in cfg and isinstance(cfg[section], dict) and key in cfg[section]:
            cfg[section][key] = _coerce(value, cfg[section][key])
    return cfg


def _coerce(raw: str, like: Any) -> Any:
    if isinstance(like, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(like, int) and not isinstance(like, bool):
        try:
            return int(raw)
        except ValueError:
            return like
    if isinstance(like, float):
        try:
            return float(raw)
        except ValueError:
            return like
    return raw


def _load_dotenv() -> None:
    """Pull .env into the environment so API keys stay out of the shell profile."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file)
        return
    except ImportError:
        pass
    # Minimal parser, so a missing python-dotenv isn't fatal.
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def load_config(path: str | Path | None = None) -> dict:
    """Load config from disk, merged over DEFAULTS, with env applied last."""
    _load_dotenv()
    cfg = copy.deepcopy(DEFAULTS)
    candidate = Path(path) if path else Path(
        os.environ.get("JARVIS_CONFIG", PROJECT_ROOT / "config.yaml")
    )
    if candidate.exists():
        if yaml is None:
            raise RuntimeError("PyYAML is required to read config.yaml (pip install pyyaml)")
        with open(candidate, "r", encoding="utf-8") as fh:
            cfg = _deep_merge(cfg, yaml.safe_load(fh) or {})
    cfg = _apply_env(cfg)
    cfg["_config_path"] = str(candidate)
    for directory in (DATA_DIR, MODELS_DIR, LOGS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    return cfg


def safe_roots(cfg: dict) -> list[Path]:
    """Expanded, existing roots JARVIS is allowed to touch."""
    roots = []
    for raw in cfg["files"]["safe_roots"]:
        p = Path(raw).expanduser()
        if p.exists():
            roots.append(p.resolve())
    return roots
