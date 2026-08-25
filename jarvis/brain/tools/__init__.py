"""Tool registry: JSON schemas for Claude, plus dispatch to implementations."""
from __future__ import annotations

import logging
from typing import Any, Callable

from . import files, shell, system, web

log = logging.getLogger(__name__)

# name -> (callable, schema)
_REGISTRY: dict[str, tuple[Callable[..., str], dict]] = {}


def tool(name: str, description: str, schema: dict) -> Callable:
    def register(fn: Callable[..., str]) -> Callable[..., str]:
        _REGISTRY[name] = (fn, {
            "name": name,
            "description": description,
            "input_schema": {"type": "object", "properties": schema.get("properties", {}),
                             "required": schema.get("required", [])},
        })
        return fn
    return register


def _reg(name: str, fn: Callable, description: str, properties: dict, required: list[str] | None = None):
    _REGISTRY[name] = (fn, {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required or [],
        },
    })


# -- files -----------------------------------------------------------------
_reg(
    "organize_files", files.organize_files,
    "Tidy a directory by sorting loose files into subfolders. ALWAYS call with "
    "dry_run=true first, describe the resulting plan to the user out loud, and "
    "only apply it once they agree. This is the tool for 'clean up my downloads' "
    "or 'organize my desktop'.",
    {
        "directory": {"type": "string", "description": "Directory to organize, e.g. '~/Downloads'"},
        "strategy": {
            "type": "string",
            "enum": ["by_type", "by_date", "by_type_then_date", "by_extension"],
            "description": "by_type sorts into Images/Documents/etc. by_date sorts into Year/Month.",
        },
        "dry_run": {"type": "boolean", "description": "True = plan only, nothing moves. Default true."},
        "recursive": {"type": "boolean", "description": "Also organize files in subfolders."},
        "older_than_days": {"type": "integer", "description": "Only touch files older than this."},
        "confirmed": {"type": "boolean", "description": "Set true only after the user verbally approved a large batch."},
    },
    ["directory"],
)
_reg(
    "undo_last_organize", files.undo_last_organize,
    "Reverse the most recent file organization, putting everything back where it was. "
    "Use when the user says 'undo that' or 'put it back'.",
    {"batch_id": {"type": "string", "description": "Specific batch to undo. Omit for the most recent."}},
)
_reg(
    "find_files", files.find_files,
    "Search for files by name pattern, age, size, or text content.",
    {
        "directory": {"type": "string", "description": "Where to search, e.g. '~/Documents'"},
        "pattern": {"type": "string", "description": "Glob pattern, e.g. '*.pdf' or '*invoice*'"},
        "contains": {"type": "string", "description": "Only match text files containing this string."},
        "newer_than_days": {"type": "number", "description": "Only files modified within this many days."},
        "min_size_mb": {"type": "number", "description": "Only files at least this large."},
        "sort_by": {"type": "string", "enum": ["modified", "size"]},
        "max_results": {"type": "integer"},
    },
    ["directory"],
)
_reg(
    "inspect_directory", files.inspect_directory,
    "Summarize what's in a directory: file counts by category, total sizes, date range. "
    "Use this before organizing so you can tell the user what you found.",
    {"directory": {"type": "string"}},
    ["directory"],
)
_reg(
    "move_file", files.move_file,
    "Move or rename a single file.",
    {"source": {"type": "string"}, "destination": {"type": "string"}},
    ["source", "destination"],
)
_reg(
    "delete_file", files.delete_file,
    "Send a file to the system trash (recoverable, never a permanent delete).",
    {"path": {"type": "string"}},
    ["path"],
)
_reg(
    "read_text_file", files.read_text_file,
    "Read the contents of a text file so you can summarize or answer questions about it.",
    {"path": {"type": "string"}, "max_chars": {"type": "integer"}},
    ["path"],
)
_reg(
    "create_folder", files.create_folder,
    "Create a new folder.",
    {"path": {"type": "string"}},
    ["path"],
)

# -- web -------------------------------------------------------------------
_reg(
    "web_search", web.web_search,
    "Search the web and read the results yourself, so you can answer out loud. "
    "Use this for questions of fact, current events, prices, or documentation.",
    {"query": {"type": "string"}, "max_results": {"type": "integer"}},
    ["query"],
)
_reg(
    "fetch_page", web.fetch_page,
    "Fetch a specific URL and read its text content.",
    {"url": {"type": "string"}, "max_chars": {"type": "integer"}},
    ["url"],
)
_reg(
    "search_web_in_browser", system.search_web_in_browser,
    "Open search results on screen in the user's browser. Use this when they want "
    "to LOOK at results ('pull up', 'show me') rather than be told the answer.",
    {
        "query": {"type": "string"},
        "engine": {"type": "string", "enum": ["google", "duckduckgo", "youtube", "github", "maps"]},
    },
    ["query"],
)
_reg(
    "open_url", system.open_url,
    "Open a URL in the user's default browser.",
    {"url": {"type": "string"}},
    ["url"],
)

# -- desktop ---------------------------------------------------------------
_reg(
    "open_application", system.open_application,
    "Launch a desktop application by name, e.g. 'Spotify', 'Terminal', 'Visual Studio Code'.",
    {"name": {"type": "string"}},
    ["name"],
)
_reg("take_screenshot", system.take_screenshot, "Capture the screen to a PNG file.", {})
_reg(
    "clipboard", system.clipboard,
    "Read the clipboard, or write text to it.",
    {"action": {"type": "string", "enum": ["read", "write"]}, "text": {"type": "string"}},
    ["action"],
)
_reg(
    "set_volume", system.set_volume,
    "Set system output volume, 0-100.",
    {"level": {"type": "integer"}},
    ["level"],
)
_reg(
    "get_system_status", system.get_system_status,
    "Report CPU, memory, disk, battery and time. Use for 'how are we looking' / 'system status'.",
    {},
)
_reg(
    "remember", system.remember,
    "Store a fact for later recall across restarts.",
    {"key": {"type": "string", "description": "Short label"}, "value": {"type": "string"}},
    ["key", "value"],
)
_reg(
    "recall", system.recall,
    "Retrieve something previously remembered. Omit key to list all labels.",
    {"key": {"type": "string"}},
)
_reg(
    "run_shell", shell.run_shell,
    "Run a shell command. Disabled unless the user turned it on in config. Anything "
    "not on the allowlist requires explicit spoken confirmation first.",
    {"command": {"type": "string"}, "confirmed": {"type": "boolean"}},
    ["command"],
)


def schemas() -> list[dict]:
    """Tool definitions in the shape the Anthropic API expects."""
    return [schema for _, schema in _REGISTRY.values()]


def dispatch(name: str, arguments: dict[str, Any], cfg: dict) -> str:
    fn, _ = _REGISTRY.get(name, (None, None))
    if fn is None:
        return f"I don't have a tool called '{name}'."
    log.info("tool: %s(%s)", name, ", ".join(f"{k}={v!r}" for k, v in arguments.items()))
    try:
        return fn(cfg, **arguments)
    except Exception as exc:  # surfaced to the model so it can recover or explain
        log.exception("tool %s failed", name)
        return f"That failed: {type(exc).__name__}: {exc}"


def tool_names() -> list[str]:
    return sorted(_REGISTRY)
