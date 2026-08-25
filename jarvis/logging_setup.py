"""Logging: a quiet console, a full file, and an optional transcript log."""
from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path

from .paths import _NullStream


def setup_logging(cfg: dict, verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else getattr(logging, cfg["logging"]["level"], logging.INFO)
    log_path = Path(cfg["logging"]["file"])
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)-24s %(message)s")
    )
    root.addHandler(file_handler)

    # In a windowed build there is no console to log to, and attaching a
    # handler to a null stream just burns cycles formatting discarded text.
    if sys.stderr is not None and not isinstance(sys.stderr, _NullStream):
        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(logging.Formatter("\033[2m%(levelname)s %(message)s\033[0m"))
        root.addHandler(console)

    # These are chatty and rarely what you're debugging.
    for noisy in ("httpx", "httpcore", "urllib3", "anthropic", "faster_whisper", "numba"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_transcript(cfg: dict, role: str, text: str) -> None:
    if not cfg["logging"]["save_transcripts"]:
        return
    path = Path(cfg["logging"]["file"]).parent / "transcript.jsonl"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "time": datetime.now().isoformat(timespec="seconds"),
            "role": role,
            "text": text,
        }) + "\n")
