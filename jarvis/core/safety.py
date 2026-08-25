"""Path guarding.

JARVIS gets to move your files around. The only thing standing between "organize
my downloads" and a very bad afternoon is this module, so it is deliberately
boring: an explicit allowlist of roots, resolved symlinks, and no exceptions.
"""
from __future__ import annotations

from pathlib import Path


class UnsafePathError(Exception):
    """Raised when an operation would touch a path outside the safe roots."""


# Directories never to descend into, checked *relative to* a safe root.
#
# The relative part matters. These names are matched only against the portion of
# the path below whichever root allowed it, never against the root's own
# ancestors - because the user vetted those ancestors when they configured the
# root. Checking the whole absolute path instead looks stricter but is simply
# wrong: on Windows every temp directory lives under
# C:\Users\<name>\AppData\Local\Temp, so a blanket "AppData" rule refuses
# paths the user explicitly authorised.
PROTECTED_NAMES = {
    ".ssh", ".gnupg", ".aws", ".config", ".git", ".password-store",
    ".kube", ".docker", ".npmrc", ".netrc",
    "Library", "System", "Windows", "Program Files", "AppData",
    "node_modules", ".venv", "venv",
}


def resolve_under(path: str | Path, roots: list[Path], *, must_exist: bool = False) -> Path:
    """Resolve `path` and assert it lives under one of `roots`.

    Resolution happens before the containment check, so
    `~/Downloads/../../.ssh/id_rsa` fails rather than sneaking through on a
    string prefix match.
    """
    if not roots:
        raise UnsafePathError(
            "No safe roots are configured. Set files.safe_roots in config.yaml."
        )
    p = Path(path).expanduser()
    # resolve(strict=False) still collapses .. and follows existing symlinks.
    p = p.resolve()
    if must_exist and not p.exists():
        raise UnsafePathError(f"Path does not exist: {p}")

    for root in roots:
        try:
            relative = p.relative_to(root)
        except ValueError:
            continue
        # Inside an authorised root - now refuse the sensitive subtrees.
        for part in relative.parts:
            if part in PROTECTED_NAMES:
                raise UnsafePathError(f"'{part}' is protected and off limits: {p}")
        return p

    allowed = ", ".join(str(r) for r in roots)
    raise UnsafePathError(f"{p} is outside the permitted roots ({allowed}).")


def is_safe(path: str | Path, roots: list[Path]) -> bool:
    try:
        resolve_under(path, roots)
        return True
    except UnsafePathError:
        return False


def unique_destination(dest: Path) -> Path:
    """If `dest` exists, return `dest` with a ' (2)' style suffix instead."""
    if not dest.exists():
        return dest
    stem, suffix, parent = dest.stem, dest.suffix, dest.parent
    n = 2
    while True:
        candidate = parent / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate
        n += 1
