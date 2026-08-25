"""File tools: find, inspect, organize, move, undo.

The organizer always works in two phases - build a plan, then apply it. The
model is instructed to show you the plan first. Every applied move is written to
a journal so "JARVIS, undo that" actually works.
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ...config import safe_roots
from ...core.safety import UnsafePathError, resolve_under, unique_destination

log = logging.getLogger(__name__)

# Extension -> folder name. Anything unmatched lands in "Other".
CATEGORIES: dict[str, tuple[str, ...]] = {
    "Images": (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".svg", ".tiff", ".raw"),
    "Video": (".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".m4v", ".flv"),
    "Audio": (".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".aiff"),
    "Documents": (".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".pages", ".epub", ".md"),
    "Spreadsheets": (".xls", ".xlsx", ".csv", ".tsv", ".numbers", ".ods"),
    "Presentations": (".ppt", ".pptx", ".key", ".odp"),
    "Archives": (".zip", ".tar", ".gz", ".rar", ".7z", ".bz2", ".xz", ".dmg", ".iso"),
    "Code": (".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".h", ".go",
             ".rs", ".rb", ".php", ".sh", ".html", ".css", ".json", ".yaml", ".yml", ".sql"),
    "Installers": (".exe", ".msi", ".pkg", ".deb", ".rpm", ".appimage"),
    "Fonts": (".ttf", ".otf", ".woff", ".woff2"),
}

_EXT_TO_CATEGORY = {ext: cat for cat, exts in CATEGORIES.items() for ext in exts}


def categorize(path: Path) -> str:
    return _EXT_TO_CATEGORY.get(path.suffix.lower(), "Other")


# -- planning --------------------------------------------------------------
def build_plan(
    directory: Path,
    strategy: str = "by_type",
    recursive: bool = False,
    include_hidden: bool = False,
    older_than_days: int | None = None,
) -> list[dict[str, str]]:
    """Compute the moves for a strategy. Pure - touches nothing on disk."""
    moves: list[dict[str, str]] = []
    entries = directory.rglob("*") if recursive else directory.iterdir()

    for entry in sorted(entries):
        if not entry.is_file():
            continue
        if not include_hidden and entry.name.startswith("."):
            continue
        if older_than_days is not None:
            age_days = (time.time() - entry.stat().st_mtime) / 86400
            if age_days < older_than_days:
                continue

        if strategy == "by_type":
            folder = directory / categorize(entry)
        elif strategy == "by_date":
            mtime = datetime.fromtimestamp(entry.stat().st_mtime)
            folder = directory / f"{mtime.year}" / f"{mtime.month:02d}-{mtime.strftime('%B')}"
        elif strategy == "by_type_then_date":
            mtime = datetime.fromtimestamp(entry.stat().st_mtime)
            folder = directory / categorize(entry) / str(mtime.year)
        elif strategy == "by_extension":
            ext = entry.suffix.lower().lstrip(".") or "no-extension"
            folder = directory / ext.upper()
        else:
            raise ValueError(f"unknown strategy: {strategy}")

        # Already filed correctly? Leave it alone.
        if entry.parent == folder:
            continue
        dest = folder / entry.name
        moves.append({
            "src": str(entry),
            "dst": str(dest),
            "reason": f"{entry.suffix.lower() or 'no ext'} -> {folder.name}",
            "size": entry.stat().st_size,
        })
    return moves


def summarize_plan(moves: list[dict[str, Any]]) -> str:
    if not moves:
        return "Nothing to move - that directory is already in order."
    buckets: dict[str, int] = {}
    total_bytes = 0
    for m in moves:
        buckets[Path(m["dst"]).parent.name] = buckets.get(Path(m["dst"]).parent.name, 0) + 1
        total_bytes += int(m.get("size", 0))
    lines = [f"{len(moves)} files ({human_size(total_bytes)}) into {len(buckets)} folders:"]
    for folder, count in sorted(buckets.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {folder}: {count}")
    sample = moves[:5]
    lines.append("Examples:")
    for m in sample:
        lines.append(f"  {Path(m['src']).name} -> {Path(m['dst']).parent.name}/")
    if len(moves) > len(sample):
        lines.append(f"  ...and {len(moves) - len(sample)} more")
    return "\n".join(lines)


def human_size(n: int) -> str:
    step = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if step < 1024 or unit == "TB":
            return f"{step:.0f} {unit}" if unit == "B" else f"{step:.1f} {unit}"
        step /= 1024
    return f"{step:.1f} TB"


# -- journal ---------------------------------------------------------------
def journal_write(cfg: dict, batch_id: str, applied: list[dict[str, str]]) -> None:
    path = Path(cfg["files"]["journal_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "batch_id": batch_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "moves": applied,
    }
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def journal_read(cfg: dict) -> list[dict]:
    path = Path(cfg["files"]["journal_path"])
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def journal_drop(cfg: dict, batch_id: str) -> None:
    path = Path(cfg["files"]["journal_path"])
    records = [r for r in journal_read(cfg) if r["batch_id"] != batch_id]
    with open(path, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")


# -- tool implementations --------------------------------------------------
def organize_files(cfg: dict, **kwargs) -> str:
    directory = kwargs.get("directory", "~/Downloads")
    strategy = kwargs.get("strategy", "by_type")
    dry_run = kwargs.get("dry_run", True)
    recursive = bool(kwargs.get("recursive", False))
    older_than_days = kwargs.get("older_than_days")

    roots = safe_roots(cfg)
    target = resolve_under(directory, roots, must_exist=True)
    if not target.is_dir():
        return f"{target} is a file, not a directory."

    moves = build_plan(
        target, strategy=strategy, recursive=recursive,
        older_than_days=older_than_days,
    )
    if not moves:
        return f"{target} is already organized - nothing to move."

    if dry_run:
        return (
            f"PLAN for {target} (strategy: {strategy}) - nothing moved yet.\n"
            f"{summarize_plan(moves)}\n\n"
            "Call organize_files again with dry_run=false to apply this."
        )

    threshold = cfg["files"]["confirm_threshold"]
    if len(moves) > threshold and not kwargs.get("confirmed", False):
        return (
            f"This would move {len(moves)} files, which is over the "
            f"{threshold}-file confirmation threshold.\n{summarize_plan(moves)}\n\n"
            "Ask the user to confirm out loud, then call again with confirmed=true."
        )

    batch_id = f"organize-{int(time.time())}"
    applied, failures = [], []
    for move in moves:
        src, dst = Path(move["src"]), Path(move["dst"])
        try:
            resolve_under(src, roots, must_exist=True)
            dst.parent.mkdir(parents=True, exist_ok=True)
            final = unique_destination(dst)
            shutil.move(str(src), str(final))
            applied.append({"src": str(src), "dst": str(final)})
        except (UnsafePathError, OSError) as exc:
            failures.append(f"{src.name}: {exc}")

    if applied:
        journal_write(cfg, batch_id, applied)
    result = f"Moved {len(applied)} files in {target}.\n{summarize_plan(moves)}"
    if failures:
        result += f"\n\n{len(failures)} failed:\n  " + "\n  ".join(failures[:10])
    result += f"\n\n(Batch {batch_id} - say 'undo that' to reverse it.)"
    return result


def undo_last_organize(cfg: dict, **kwargs) -> str:
    records = journal_read(cfg)
    if not records:
        return "There's nothing in the journal to undo."
    batch_id = kwargs.get("batch_id") or records[-1]["batch_id"]
    record = next((r for r in records if r["batch_id"] == batch_id), None)
    if record is None:
        return f"No batch named {batch_id} in the journal."

    roots = safe_roots(cfg)
    restored, failures = 0, []
    for move in reversed(record["moves"]):
        src, dst = Path(move["src"]), Path(move["dst"])
        try:
            if not dst.exists():
                failures.append(f"{dst.name} is no longer where I left it")
                continue
            resolve_under(dst, roots, must_exist=True)
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(unique_destination(src)))
            restored += 1
        except (UnsafePathError, OSError) as exc:
            failures.append(f"{dst.name}: {exc}")

    journal_drop(cfg, batch_id)
    # Clean up folders the organize run created and emptied out again.
    for move in record["moves"]:
        parent = Path(move["dst"]).parent
        try:
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass

    msg = f"Restored {restored} files from batch {batch_id}."
    if failures:
        msg += f"\n{len(failures)} could not be restored:\n  " + "\n  ".join(failures[:10])
    return msg


def find_files(cfg: dict, **kwargs) -> str:
    directory = kwargs.get("directory", "~/Downloads")
    pattern = kwargs.get("pattern", "*")
    contains = kwargs.get("contains")
    max_results = int(kwargs.get("max_results", 40))
    newer_than_days = kwargs.get("newer_than_days")
    min_size_mb = kwargs.get("min_size_mb")
    sort_by = kwargs.get("sort_by", "modified")

    roots = safe_roots(cfg)
    target = resolve_under(directory, roots, must_exist=True)
    hits = []
    for entry in target.rglob(pattern):
        if not entry.is_file() or entry.name.startswith("."):
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        if newer_than_days is not None:
            if (time.time() - stat.st_mtime) / 86400 > float(newer_than_days):
                continue
        if min_size_mb is not None and stat.st_size < float(min_size_mb) * 1024 * 1024:
            continue
        if contains:
            if entry.suffix.lower() not in CATEGORIES["Documents"] + CATEGORIES["Code"]:
                continue
            try:
                text = entry.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if contains.lower() not in text.lower():
                continue
        hits.append((entry, stat))

    if sort_by == "size":
        hits.sort(key=lambda h: -h[1].st_size)
    else:
        hits.sort(key=lambda h: -h[1].st_mtime)

    if not hits:
        return f"No files matching '{pattern}' under {target}."
    lines = [f"{len(hits)} match(es) under {target} (showing {min(len(hits), max_results)}):"]
    for entry, stat in hits[:max_results]:
        when = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d")
        rel = entry.relative_to(target)
        lines.append(f"  {rel}  [{human_size(stat.st_size)}, {when}]")
    return "\n".join(lines)


def inspect_directory(cfg: dict, **kwargs) -> str:
    directory = kwargs.get("directory", "~/Downloads")
    roots = safe_roots(cfg)
    target = resolve_under(directory, roots, must_exist=True)

    by_category: dict[str, list[int]] = {}
    subdirs, total, oldest, newest = 0, 0, None, None
    for entry in target.iterdir():
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            subdirs += 1
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        cat = categorize(entry)
        by_category.setdefault(cat, []).append(stat.st_size)
        total += 1
        oldest = min(oldest, stat.st_mtime) if oldest else stat.st_mtime
        newest = max(newest, stat.st_mtime) if newest else stat.st_mtime

    if not total and not subdirs:
        return f"{target} is empty."
    lines = [f"{target}: {total} loose files, {subdirs} subfolders"]
    for cat, sizes in sorted(by_category.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"  {cat}: {len(sizes)} files, {human_size(sum(sizes))}")
    if oldest and newest:
        lines.append(
            f"  Oldest: {datetime.fromtimestamp(oldest):%Y-%m-%d}, "
            f"newest: {datetime.fromtimestamp(newest):%Y-%m-%d}"
        )
    return "\n".join(lines)


def move_file(cfg: dict, **kwargs) -> str:
    roots = safe_roots(cfg)
    src = resolve_under(kwargs["source"], roots, must_exist=True)
    dst = resolve_under(kwargs["destination"], roots)
    if dst.is_dir():
        dst = dst / src.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    final = unique_destination(dst)
    shutil.move(str(src), str(final))
    batch_id = f"move-{int(time.time())}"
    journal_write(cfg, batch_id, [{"src": str(src), "dst": str(final)}])
    return f"Moved {src.name} -> {final}"


def delete_file(cfg: dict, **kwargs) -> str:
    """Deletes go to the OS trash. There is deliberately no hard-delete tool."""
    roots = safe_roots(cfg)
    target = resolve_under(kwargs["path"], roots, must_exist=True)
    if not cfg["files"]["use_trash"]:
        return "Trash is disabled in config, and I won't permanently delete files."
    try:
        from send2trash import send2trash

        send2trash(str(target))
        return f"Moved {target.name} to the trash. It's recoverable from there."
    except ImportError:
        return "send2trash isn't installed, so I can't safely trash files. `pip install send2trash`."


def read_text_file(cfg: dict, **kwargs) -> str:
    roots = safe_roots(cfg)
    target = resolve_under(kwargs["path"], roots, must_exist=True)
    max_chars = int(kwargs.get("max_chars", 8000))
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Couldn't read {target.name}: {exc}"
    if len(text) > max_chars:
        return text[:max_chars] + f"\n\n[truncated - {len(text) - max_chars} more characters]"
    return text or "(file is empty)"


def create_folder(cfg: dict, **kwargs) -> str:
    roots = safe_roots(cfg)
    target = resolve_under(kwargs["path"], roots)
    target.mkdir(parents=True, exist_ok=True)
    return f"Created {target}"
