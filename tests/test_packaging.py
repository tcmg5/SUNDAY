"""Packaging concerns that only bite in a frozen build.

None of this can be caught by running from source - which is exactly why it
needs tests. A windowed PyInstaller build has no stdout, and its install
directory is read-only.
"""
import sys
from pathlib import Path

import pytest

from jarvis import paths


# ── stream handling ──────────────────────────────────────────────────────
def test_null_streams_replace_none(monkeypatch):
    """PyInstaller sets stdout/stderr to None with console=False; print() on
    None raises AttributeError and takes the whole app down."""
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    paths.attach_null_streams()

    assert sys.stdout is not None and sys.stderr is not None
    print("this must not raise")
    print("nor this", file=sys.stderr)
    sys.stdout.flush()


def test_null_streams_leave_real_streams_alone(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(sys, "stdout", sentinel)
    monkeypatch.setattr(sys, "stderr", sentinel)
    paths.attach_null_streams()
    assert sys.stdout is sentinel and sys.stderr is sentinel


def test_null_stream_satisfies_the_stream_protocol():
    stream = paths._NullStream()
    assert stream.write("anything") == 0
    assert stream.flush() is None
    assert stream.isatty() is False


def test_logging_setup_survives_a_windowed_build(monkeypatch, tmp_path):
    """setup_logging must not attach a StreamHandler to a dead stream."""
    import logging

    from jarvis.logging_setup import setup_logging

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    paths.attach_null_streams()

    cfg = {"logging": {"level": "INFO", "file": str(tmp_path / "j.log"),
                       "save_transcripts": False}}
    setup_logging(cfg)
    logging.getLogger("test").info("must not raise")

    handlers = logging.getLogger().handlers
    assert any(isinstance(h, logging.FileHandler) for h in handlers), "file log missing"
    stream_only = [
        h for h in handlers
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
    ]
    assert not stream_only, "attached a console handler with no console to write to"
    logging.getLogger().handlers.clear()


# ── path resolution ──────────────────────────────────────────────────────
def test_source_mode_keeps_state_beside_the_code():
    assert not paths.is_frozen()
    assert paths.CONFIG_PATH.name == "config.yaml"
    assert paths.STATE_ROOT == Path(paths.__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "platform,env,expected_tail",
    [
        ("win32", {"APPDATA": r"C:\Users\t\AppData\Roaming"}, "JARVIS"),
        ("darwin", {}, "JARVIS"),
        ("linux", {"XDG_DATA_HOME": "/home/t/.local/share"}, "JARVIS"),
    ],
)
def test_user_data_dir_per_platform(monkeypatch, platform, env, expected_tail):
    monkeypatch.setattr(sys, "platform", platform)
    for key in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    result = paths.user_data_dir()
    assert result.name == expected_tail
    if platform == "darwin":
        assert "Application Support" in str(result)


def test_frozen_state_moves_out_of_the_install_directory(monkeypatch, tmp_path):
    """Program Files is read-only for normal users, so a frozen build must not
    try to write config or models next to the executable."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))

    assert paths.is_frozen()
    assert paths.bundle_dir() == tmp_path / "bundle"
    assert paths._root() == tmp_path / "Roaming" / "JARVIS"
    # The writable root must be somewhere other than the bundle.
    assert paths._root() != paths.bundle_dir()


def test_bundled_resource_returns_none_when_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert paths.bundled_resource("nope.onnx") is None
    (tmp_path / "here.txt").write_text("x")
    assert paths.bundled_resource("here.txt") == tmp_path / "here.txt"


# ── build definition ─────────────────────────────────────────────────────
SPEC = Path(__file__).resolve().parent.parent / "jarvis.spec"


def test_spec_builds_both_a_windowed_and_a_console_executable():
    """The console twin is how anyone diagnoses a silent failure."""
    text = SPEC.read_text()
    assert 'build_exe("JARVIS", console=False)' in text
    assert 'build_exe("JARVIS-console", console=True)' in text
    assert "exe_gui," in text and "exe_console," in text


def test_spec_collects_the_packages_that_load_data_at_runtime():
    text = SPEC.read_text()
    for package in ("openwakeword", "onnxruntime", "ctranslate2", "faster_whisper", "piper"):
        assert package in text, f"{package} is not collected; it will be missing at runtime"


def test_spec_does_not_exclude_something_we_import():
    """An over-eager exclude list is the classic way to ship a broken build."""
    text = SPEC.read_text()
    excludes = text[text.index("excludes=["):text.index("]", text.index("excludes=["))]
    for needed in ("PySide6.QtWidgets", "PySide6.QtCore", "PySide6.QtGui",
                   "numpy", "scipy", "sklearn", "anthropic"):
        assert needed not in excludes, f"{needed} is excluded but the app needs it"
