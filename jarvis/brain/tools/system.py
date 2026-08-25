"""Desktop control: open things, screenshot, clipboard, volume, notes.

Everything here is per-OS and degrades gracefully - if a capability isn't
available on this machine, the tool says so rather than throwing.
"""
from __future__ import annotations

import json
import logging
import platform
import shutil
import subprocess
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path

from ...config import DATA_DIR

log = logging.getLogger(__name__)
SYSTEM = platform.system()  # Darwin | Windows | Linux


def open_url(cfg: dict, **kwargs) -> str:
    url = kwargs.get("url", "").strip()
    if not url:
        return "I need a URL to open."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url} in your browser."


def search_web_in_browser(cfg: dict, **kwargs) -> str:
    """For when you want the results on screen, not read aloud."""
    query = kwargs.get("query", "").strip()
    if not query:
        return "I need something to search for."
    engine = kwargs.get("engine", "google")
    templates = {
        "google": "https://www.google.com/search?q=",
        "duckduckgo": "https://duckduckgo.com/?q=",
        "youtube": "https://www.youtube.com/results?search_query=",
        "github": "https://github.com/search?q=",
        "maps": "https://www.google.com/maps/search/",
    }
    url = templates.get(engine, templates["google"]) + urllib.parse.quote(query)
    webbrowser.open(url)
    return f"Pulled up {engine} results for '{query}'."


def open_application(cfg: dict, **kwargs) -> str:
    name = kwargs.get("name", "").strip()
    if not name:
        return "Which application?"
    try:
        if SYSTEM == "Darwin":
            subprocess.run(["open", "-a", name], check=True, capture_output=True)
        elif SYSTEM == "Windows":
            subprocess.run(["cmd", "/c", "start", "", name], check=True, capture_output=True)
        else:
            if not shutil.which(name.lower()):
                return f"I can't find '{name}' on your PATH."
            subprocess.Popen(
                [name.lower()], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        return f"Opening {name}."
    except subprocess.CalledProcessError:
        return f"I couldn't open '{name}' - it may not be installed under that name."


def take_screenshot(cfg: dict, **kwargs) -> str:
    shots = DATA_DIR / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    path = shots / f"screen-{datetime.now():%Y%m%d-%H%M%S}.png"
    try:
        if SYSTEM == "Darwin":
            subprocess.run(["screencapture", "-x", str(path)], check=True)
        elif SYSTEM == "Windows":
            script = (
                "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
                "$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
                "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
                "$g = [System.Drawing.Graphics]::FromImage($bmp); "
                "$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size); "
                f"$bmp.Save('{path}')"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
        else:
            for tool, args in (
                ("grim", [str(path)]),
                ("scrot", [str(path)]),
                ("import", ["-window", "root", str(path)]),
            ):
                if shutil.which(tool):
                    subprocess.run([tool, *args], check=True)
                    break
            else:
                return "No screenshot tool found (install grim, scrot, or imagemagick)."
        return f"Screenshot saved to {path}"
    except subprocess.CalledProcessError as exc:
        return f"Screenshot failed: {exc}"


def clipboard(cfg: dict, **kwargs) -> str:
    action = kwargs.get("action", "read")
    text = kwargs.get("text", "")
    try:
        if action == "write":
            if SYSTEM == "Darwin":
                subprocess.run(["pbcopy"], input=text, text=True, check=True)
            elif SYSTEM == "Windows":
                subprocess.run(["clip"], input=text, text=True, check=True)
            elif shutil.which("xclip"):
                subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, check=True)
            elif shutil.which("wl-copy"):
                subprocess.run(["wl-copy"], input=text, text=True, check=True)
            else:
                return "No clipboard tool available (install xclip or wl-clipboard)."
            return "Copied to your clipboard."

        if SYSTEM == "Darwin":
            out = subprocess.run(["pbpaste"], capture_output=True, text=True, check=True)
        elif SYSTEM == "Windows":
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                capture_output=True, text=True, check=True,
            )
        elif shutil.which("xclip"):
            out = subprocess.run(
                ["xclip", "-selection", "clipboard", "-o"],
                capture_output=True, text=True, check=True,
            )
        elif shutil.which("wl-paste"):
            out = subprocess.run(["wl-paste"], capture_output=True, text=True, check=True)
        else:
            return "No clipboard tool available."
        return f"Clipboard contains:\n{out.stdout.strip() or '(empty)'}"
    except subprocess.CalledProcessError as exc:
        return f"Clipboard operation failed: {exc}"


def set_volume(cfg: dict, **kwargs) -> str:
    level = kwargs.get("level")
    if level is None:
        return "What volume level? 0 to 100."
    level = max(0, min(100, int(level)))
    try:
        if SYSTEM == "Darwin":
            subprocess.run(
                ["osascript", "-e", f"set volume output volume {level}"], check=True
            )
        elif SYSTEM == "Windows":
            return "Windows volume control needs the pycaw package; not wired up."
        elif shutil.which("pactl"):
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"], check=True
            )
        elif shutil.which("amixer"):
            subprocess.run(["amixer", "set", "Master", f"{level}%"], check=True)
        else:
            return "No volume control available on this system."
        return f"Volume set to {level}%."
    except subprocess.CalledProcessError as exc:
        return f"Couldn't change the volume: {exc}"


def get_system_status(cfg: dict, **kwargs) -> str:
    """The 'all systems nominal' report."""
    lines = [f"{platform.system()} {platform.release()} on {platform.machine()}"]
    try:
        import psutil

        cpu = psutil.cpu_percent(interval=0.4)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(str(Path.home()))
        lines.append(f"CPU {cpu:.0f}%, memory {mem.percent:.0f}% of {mem.total / 1e9:.0f} GB")
        lines.append(f"Disk {disk.percent:.0f}% used, {disk.free / 1e9:.0f} GB free")
        battery = psutil.sensors_battery()
        if battery:
            state = "charging" if battery.power_plugged else "on battery"
            lines.append(f"Battery {battery.percent:.0f}% ({state})")
    except ImportError:
        lines.append("(install psutil for CPU, memory and battery telemetry)")
    lines.append(f"Local time {datetime.now():%A %d %B %Y, %H:%M}")
    return "\n".join(lines)


# -- lightweight persistent memory ----------------------------------------
MEMORY_PATH = DATA_DIR / "memory.json"


def _load_memory() -> dict:
    if MEMORY_PATH.exists():
        try:
            return json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def remember(cfg: dict, **kwargs) -> str:
    key = kwargs.get("key", "").strip().lower()
    value = kwargs.get("value", "").strip()
    if not key or not value:
        return "I need both a label and something to store under it."
    memory = _load_memory()
    memory[key] = {"value": value, "stored": datetime.now().isoformat(timespec="seconds")}
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_PATH.write_text(json.dumps(memory, indent=2), encoding="utf-8")
    return f"Noted - '{key}'."


def recall(cfg: dict, **kwargs) -> str:
    memory = _load_memory()
    if not memory:
        return "I haven't been asked to remember anything yet."
    key = kwargs.get("key", "").strip().lower()
    if not key:
        return "I'm holding notes on: " + ", ".join(sorted(memory))
    if key in memory:
        return f"{key}: {memory[key]['value']}"
    partial = [k for k in memory if key in k or k in key]
    if partial:
        return "\n".join(f"{k}: {memory[k]['value']}" for k in partial)
    return f"Nothing stored under '{key}'."
