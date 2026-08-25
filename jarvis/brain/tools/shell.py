"""Guarded shell access. Off by default - see shell.enabled in config.yaml."""
from __future__ import annotations

import logging
import shlex
import subprocess

log = logging.getLogger(__name__)

# Substrings that mean "no" regardless of allowlist or confirmation.
FORBIDDEN = (
    "rm -rf /", "mkfs", "dd if=", ":(){", "shutdown", "reboot", "> /dev/sd",
    "chmod -R 777 /", "curl | sh", "wget | sh", "sudo rm", "diskutil erase",
    "format c:", "del /f /s /q c:\\",
)


def run_shell(cfg: dict, **kwargs) -> str:
    if not cfg["shell"]["enabled"]:
        return (
            "Shell access is disabled. If you want me running commands, "
            "set shell.enabled to true in config.yaml."
        )
    command = kwargs.get("command", "").strip()
    if not command:
        return "No command given."

    lowered = command.lower()
    for bad in FORBIDDEN:
        if bad in lowered:
            return f"I won't run that - it matches the forbidden pattern '{bad}'."

    try:
        program = shlex.split(command)[0]
    except ValueError:
        return "That command isn't parseable."

    allowlisted = program in cfg["shell"]["allowlist"]
    if not allowlisted and not kwargs.get("confirmed", False):
        return (
            f"'{program}' isn't on the shell allowlist. Read the command back to "
            "the user, get a spoken yes, then call again with confirmed=true.\n"
            f"Command: {command}"
        )

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=cfg["shell"]["timeout_sec"],
        )
    except subprocess.TimeoutExpired:
        return f"Command timed out after {cfg['shell']['timeout_sec']}s."

    output = (result.stdout or "").strip()
    errors = (result.stderr or "").strip()
    parts = [f"exit code {result.returncode}"]
    if output:
        parts.append(output[:4000])
    if errors:
        parts.append(f"stderr:\n{errors[:2000]}")
    return "\n".join(parts)
