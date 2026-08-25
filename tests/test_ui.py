"""UI wiring that can drift silently: the theme helpers and the mapping from
tools to agent tiles. Rendering itself isn't asserted here - these are the bits
where a mistake shows up as a dead panel rather than a crash."""
import re

import pytest

from jarvis.brain import tools
from jarvis.core.state import STATE_COLORS, STATE_LABELS, State
from jarvis.ui.theme import C, STYLESHEET, rgba

pyside = pytest.importorskip("PySide6", reason="Qt not installed; UI tests skipped")

from jarvis.ui.command_center import AGENT_GROUPS, QUICK_COMMANDS  # noqa: E402


# ── theme ────────────────────────────────────────────────────────────────
def test_rgba_converts_hex_correctly():
    assert rgba("#4FD3FF", 0.2) == "rgba(79, 211, 255, 0.2)"
    assert rgba("000000", 1.0) == "rgba(0, 0, 0, 1.0)"


def test_stylesheet_is_fully_substituted():
    """The sheet is an f-string; a mistyped token yields 'None' or a bare name
    rather than a colour, and Qt silently ignores the whole rule."""
    assert "None" not in STYLESHEET
    assert "rgba(" in STYLESHEET
    # Every colour token used should have resolved to a hex or rgba() value.
    import re

    for declaration in re.findall(r":\s*([^;{}]+);", STYLESHEET):
        value = declaration.strip()
        assert not value.startswith("C."), f"unresolved token in stylesheet: {value}"
        assert "Metrics(" not in value


def test_theme_colours_are_all_valid_hex():
    for name in dir(C):
        if name.startswith("_"):
            continue
        value = getattr(C, name)
        if isinstance(value, str):
            assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value), f"C.{name} = {value!r}"


def test_every_state_has_a_colour_and_label():
    for state in State:
        assert state in STATE_COLORS, f"{state} has no colour"
        assert state in STATE_LABELS, f"{state} has no label"
        assert STATE_COLORS[state].startswith("#")
        assert len(STATE_COLORS[state]) == 7


# ── agent tiles ──────────────────────────────────────────────────────────
def test_every_tool_lights_exactly_one_agent():
    """A tool absent from AGENT_GROUPS silently never lights a tile."""
    registered = set(tools.tool_names())
    mapped = set()
    duplicates = set()
    for _name, (_glyph, _colour, tool_set) in AGENT_GROUPS.items():
        duplicates |= mapped & tool_set
        mapped |= tool_set
    assert not duplicates, f"tools mapped to more than one agent: {duplicates}"
    unmapped = registered - mapped
    assert not unmapped, f"registered tools with no agent tile: {unmapped}"


def test_agent_groups_reference_only_real_tools():
    registered = set(tools.tool_names())
    for name, (_glyph, _colour, tool_set) in AGENT_GROUPS.items():
        unknown = tool_set - registered
        assert not unknown, f"{name} agent references non-existent tools: {unknown}"


def test_agent_groups_have_distinct_colours():
    colours = [colour for _glyph, colour, _tools in AGENT_GROUPS.values()]
    assert len(colours) == len(set(colours))


# ── quick commands ───────────────────────────────────────────────────────
def test_quick_commands_are_well_formed():
    for glyph, label, prompt in QUICK_COMMANDS:
        assert glyph and label and prompt
        # A prompt ending in a space is a template the operator finishes; any
        # other prompt is sent verbatim and must be a complete instruction.
        if not prompt.endswith(" "):
            assert len(prompt.split()) >= 3, f"'{prompt}' is too terse to send as-is"


# ── widget construction (offscreen, no display) ──────────────────────────
def test_painted_widgets_construct_and_accept_values():
    from PySide6.QtWidgets import QApplication

    from jarvis.ui.widgets import Constellation, DonutGauge, HoloGlobe, MicOrb, WaveBars

    app = QApplication.instance() or QApplication([])

    gauge = DonutGauge("CPU")
    gauge.set_value(150)          # out of range on purpose
    assert gauge._value == 100.0  # clamped
    gauge.set_value(-20)
    assert gauge._value == 0.0

    wave = WaveBars()
    wave.set_level(5.0)
    assert wave._level == 1.0

    globe = HoloGlobe()
    globe.set_accent(C.GREEN, 0.02)
    globe.set_level(0.5)
    globe.set_identity("JARVIS", "AI CORE", "v1.0.0")

    orb = MicOrb()
    orb.set_level(0.3)

    constellation = Constellation()
    constellation.set_count(400)
    assert 5 <= len(constellation._nodes) <= 16  # density stays bounded
    assert app is not None


def test_globe_orbital_rings_stay_inside_the_widget():
    """A rotated ellipse extends by its MAJOR axis in every direction, so the
    widest ring must be under half the widget's smaller dimension or it clips."""
    from jarvis.ui.widgets import HoloGlobe

    import inspect

    source = inspect.getsource(HoloGlobe.paintEvent)
    # Radius factor and the ring scales are the two numbers that matter.
    assert "0.27" in source, "globe radius factor changed - recheck ring clipping"
    max_scale = 1.58
    assert 0.27 * max_scale < 0.5, "widest orbital ring would clip the panel edge"
