"""Where things live, in both worlds.

Run from a source checkout, JARVIS keeps its config, models and logs beside the
code - convenient while developing. Installed as a packaged application, it
must not: Program Files is read-only for normal users, and a .app bundle is
signed. So when frozen, everything writable moves to the per-user data
directory the platform expects.

    source :  <repo>/config.yaml, <repo>/data, <repo>/models, <repo>/logs
    frozen :  %APPDATA%\\JARVIS\\...                        (Windows)
              ~/Library/Application Support/JARVIS/...    (macOS)
              ~/.local/share/JARVIS/...                   (Linux)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "JARVIS"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle rather than source."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def bundle_dir() -> Path:
    """Read-only directory holding bundled resources (models we ship, etc.)."""
    if is_frozen():
        return Path(sys._MEIPASS)  # noqa: SLF001 - PyInstaller's documented API
    return Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    """Writable per-user directory, created on demand."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_NAME


def _root() -> Path:
    return user_data_dir() if is_frozen() else Path(__file__).resolve().parent.parent


PROJECT_ROOT = bundle_dir()
STATE_ROOT = _root()

CONFIG_PATH = STATE_ROOT / "config.yaml"
ENV_PATH = STATE_ROOT / ".env"
DATA_DIR = STATE_ROOT / "data"
MODELS_DIR = STATE_ROOT / "models"
LOGS_DIR = STATE_ROOT / "logs"


def ensure_dirs() -> None:
    for directory in (STATE_ROOT, DATA_DIR, MODELS_DIR, LOGS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def bundled_resource(*parts: str) -> Path | None:
    """Look up a file shipped inside the bundle. None if it isn't there."""
    candidate = bundle_dir().joinpath(*parts)
    return candidate if candidate.exists() else None


class _NullStream:
    """Stand-in for stdout/stderr in a windowed build.

    PyInstaller sets sys.stdout and sys.stderr to None when console=False, so
    any print() or logging StreamHandler raises AttributeError on None.write.
    A silent sink is the difference between a working app and one that dies at
    the first log line.
    """

    def write(self, _text):  # noqa: D102
        return 0

    def flush(self):  # noqa: D102
        return None

    def isatty(self):  # noqa: D102
        return False


def attach_null_streams() -> None:
    """Give a windowed build somewhere harmless to write."""
    if sys.stdout is None:
        sys.stdout = _NullStream()
    if sys.stderr is None:
        sys.stderr = _NullStream()
