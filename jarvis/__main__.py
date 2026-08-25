"""Command line entry point.

    python -m jarvis            # command center + voice (the normal way)
    python -m jarvis --ui hud   # compact always-on-top overlay instead
    python -m jarvis --text     # keyboard only, no microphone
    python -m jarvis doctor     # check every dependency and key
    python -m jarvis devices    # list audio devices
    python -m jarvis voices     # list JARVIS-suitable voices
    python -m jarvis say "..."  # test the voice
"""
from __future__ import annotations

import argparse
import sys

from .config import load_config, safe_roots
from .logging_setup import setup_logging
from .paths import configure_console, is_frozen


def main(argv: list[str] | None = None) -> int:
    # Must happen before any output: a windowed build has no streams at all,
    # and a Windows console cannot encode what we print until reconfigured.
    configure_console()
    parser = argparse.ArgumentParser(prog="jarvis", description="Your desktop AI assistant.")
    parser.add_argument("command", nargs="?", default="run",
                        choices=["run", "doctor", "devices", "voices", "say"])
    parser.add_argument("text", nargs="*", help="Text for the 'say' command.")
    parser.add_argument("--config", help="Path to config.yaml")
    parser.add_argument("--ui", choices=["command_center", "hud", "console", "none"],
                        help="Override UI mode")
    parser.add_argument("--text-mode", "--text", dest="text_mode", action="store_true",
                        help="Type commands instead of speaking them")
    parser.add_argument("--no-wake", action="store_true", help="Disable the wake word")
    parser.add_argument("--no-voice", action="store_true", help="Silence TTS output")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", action="store_true",
                        help="Machine-readable doctor output")
    parser.add_argument("--setup", action="store_true",
                        help="Re-run first-time setup (API key, voice, models)")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    if args.ui:
        cfg["ui"]["mode"] = args.ui
    if args.no_wake:
        cfg["wake"]["enabled"] = False
    if args.no_voice:
        cfg["tts"]["engine"] = "none"
    setup_logging(cfg, args.verbose)

    if args.command == "doctor":
        return doctor(cfg, as_json=args.json)
    if args.command == "devices":
        return devices()
    if args.command == "voices":
        return voices(cfg)
    if args.command == "say":
        return say(cfg, " ".join(args.text) or "All systems are functioning within normal parameters.")
    if args.setup:
        from .ui.first_run import run_first_run

        if not run_first_run(cfg):
            return 0
    return run(cfg, args)


def run(cfg: dict, args) -> int:
    from .core.assistant import Assistant

    # A packaged build has no .env to edit, so ask for the key in the UI.
    if cfg["ui"]["mode"] in ("command_center", "hud") and not args.text_mode:
        try:
            from .ui.first_run import needs_first_run, run_first_run

            if needs_first_run(cfg) and not run_first_run(cfg):
                print("Setup cancelled.")
                return 0
        except ImportError:
            pass  # no Qt - the console path reports the missing key itself

    assistant = Assistant(cfg)
    try:
        if args.text_mode:
            from .ui.console import run_text_mode

            return run_text_mode(assistant, cfg)
        mode = cfg["ui"]["mode"]
        if mode in ("command_center", "hud"):
            try:
                if mode == "command_center":
                    from .ui.command_center import run_command_center

                    return run_command_center(assistant, cfg)
                from .ui.hud import run_hud

                return run_hud(assistant, cfg)
            except ImportError as exc:
                print(f"Qt unavailable ({exc}); falling back to console.\n")
            except RuntimeError as exc:
                print(f"{mode} unavailable ({exc}); falling back to console.\n")
        from .ui.console import run_console

        return run_console(assistant, cfg)
    except KeyboardInterrupt:
        assistant.stop()
        return 0
    except Exception as exc:
        print(f"\n\033[91mFailed to start: {exc}\033[0m")
        print("Run `python -m jarvis doctor` to find out what's missing.")
        return 1


def doctor(cfg: dict, as_json: bool = False) -> int:
    """Check every moving part and say exactly what's wrong with each."""
    results: dict[str, dict] = {}
    quiet = as_json

    if not quiet:
        print("\n\033[36mJARVIS system check\033[0m\n" + "─" * 52)
    problems = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal problems
        # JSON keeps the whole message; only the terminal view is trimmed.
        results[label] = {"ok": bool(ok), "detail": detail}
        if not quiet:
            mark = "\033[92m✓\033[0m" if ok else "\033[91m✗\033[0m"
            print(f" {mark} {label:<26} {detail[:70]}")
        if not ok:
            problems += 1

    def section(title: str) -> None:
        if not quiet:
            print(f"\n\033[1m{title}\033[0m")

    def probe(module: str, label: str, hint: str) -> None:
        """Import a module and, when it fails, say why rather than guessing.

        A frozen build fails here for reasons a source checkout never does - a
        missing data file, a native library that didn't get collected - and
        "pip install X" is actively misleading advice in that case.
        """
        try:
            __import__(module)
            check(label, True)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, ImportError) and not is_frozen():
                check(label, False, hint)
            else:
                # Collapse the multi-line banners some libraries emit.
                check(label, False, " ".join(reason.split()))

    section("Core")
    check("Python", sys.version_info >= (3, 9), f"{sys.version.split()[0]}")
    for module, label in (
        ("numpy", "numpy"), ("anthropic", "anthropic"), ("yaml", "PyYAML"),
        ("httpx", "httpx"),
    ):
        probe(module, label, "pip install -r requirements.txt")

    section("Audio in")
    # Two separate questions: is the library present, and is there a mic?
    # A build server answers yes/no; only the first is ever a packaging fault.
    probe("sounddevice", "sounddevice", "pip install sounddevice")
    if results.get("sounddevice", {}).get("ok"):
        try:
            import sounddevice as sd

            default_in = sd.query_devices(kind="input")
            check("microphone", True, default_in["name"][:40])
        except Exception as exc:
            check("microphone", False, f"no input device ({str(exc)[:44]})")
    for module, label, hint in (
        ("openwakeword", "openwakeword", "pip install openwakeword"),
        ("faster_whisper", "faster-whisper", "pip install faster-whisper"),
    ):
        probe(module, label, hint)
    # Optional: absence is fine, so this never counts as a problem.
    try:
        import webrtcvad  # noqa: F401

        check("voice detection", True, "webrtcvad")
    except ImportError:
        check("voice detection", True, "built-in (webrtcvad not installed)")

    section("Voice out")
    engine = cfg["tts"]["engine"]
    if engine == "piper":
        probe("piper", "piper", "pip install piper-tts")
        if results.get("piper", {}).get("ok"):
            results["piper"]["detail"] = cfg["tts"]["piper_voice"]
        from .config import MODELS_DIR

        model = MODELS_DIR / "piper" / f"{cfg['tts']['piper_voice']}.onnx"
        check("voice model", model.exists(),
              str(model) if model.exists() else "will download on first run")
    elif engine == "elevenlabs":
        check("ELEVENLABS_API_KEY", bool(cfg["secrets"]["elevenlabs_api_key"]), "")
        check("voice id set", bool(cfg["tts"]["elevenlabs_voice_id"]), "")

    section("Brain")
    check("ANTHROPIC_API_KEY", bool(cfg["secrets"]["anthropic_api_key"]),
          "export ANTHROPIC_API_KEY=..." if not cfg["secrets"]["anthropic_api_key"] else cfg["assistant"]["model"])

    section("UI")
    try:
        import PySide6  # noqa: F401

        check("PySide6", True, f"mode: {cfg['ui']['mode']}")
    except Exception as exc:
        check("PySide6", False, f"{type(exc).__name__}: {exc}"[:70])

    section("File access")
    roots = safe_roots(cfg)
    check("safe roots", bool(roots), ", ".join(str(r) for r in roots) or "none exist!")

    if as_json:
        import json

        print(json.dumps({
            "frozen": is_frozen(),
            "problems": problems,
            "checks": results,
        }, indent=2))
        return 1 if problems else 0

    print("\n" + "─" * 52)
    if problems:
        print(f" \033[91m{problems} problem(s) found.\033[0m See hints above.\n")
    else:
        print(" \033[92mAll systems nominal.\033[0m Run `python -m jarvis` to start.\n")
    return 1 if problems else 0


def devices() -> int:
    from .audio.mic import list_devices

    print("\nAudio devices:\n")
    print(list_devices())
    print("\nSet audio.input_device / audio.output_device in config.yaml to pick one.\n")
    return 0


def voices(cfg: dict) -> int:
    from .audio.tts import RECOMMENDED_PIPER_VOICES

    print("\n\033[36mVoices suited to a JARVIS read\033[0m (free, local, via piper)\n")
    current = cfg["tts"]["piper_voice"]
    for voice_id, note in RECOMMENDED_PIPER_VOICES:
        marker = "\033[92m→\033[0m" if voice_id == current else " "
        print(f" {marker} {voice_id:<38} {note}")
    print("\n Set tts.piper_voice in config.yaml, then:  python -m jarvis say \"test\"")
    print(" For the closest match to the films, use ElevenLabs — see README.\n")
    return 0


def say(cfg: dict, text: str) -> int:
    from .audio.tts import Speaker

    print(f"\nSpeaking via {cfg['tts']['engine']}: \"{text}\"\n")
    Speaker(cfg).say(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
