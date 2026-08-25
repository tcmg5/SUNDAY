"""Visual language for the command center.

One palette, one type scale, one place to change any of it. Everything else in
the UI pulls from here so the whole surface stays coherent.
"""
from __future__ import annotations

from dataclasses import dataclass


class C:
    """Colour tokens. Deep navy ground, cyan instrumentation, status accents."""

    # Ground
    VOID = "#04080F"          # deepest ground, behind everything
    DEEP = "#060D18"          # app background
    PANEL = "#0A1524"         # panel fill
    PANEL_HI = "#0E1C2E"      # raised / hover fill
    INSET = "#071019"         # sunken wells (feeds, inputs)

    # Structure
    EDGE = "#12283D"          # quiet borders
    EDGE_LIT = "#1C4763"      # lit borders
    GRID = "#0D1B2A"          # background grid lines

    # Cyan family - the instrument colour
    CYAN = "#4FD3FF"
    CYAN_BRIGHT = "#8AE9FF"
    CYAN_DIM = "#2A8FB8"
    CYAN_DEEP = "#14556F"

    # Text
    TEXT = "#DCEBF7"
    TEXT_MUTED = "#7C93A8"
    TEXT_FAINT = "#4A6076"

    # Status accents
    GREEN = "#34D399"
    AMBER = "#FBBF24"
    RED = "#F87171"
    PURPLE = "#A78BFA"
    ORANGE = "#FB923C"
    BLUE = "#60A5FA"
    PINK = "#F472B6"


# Font stacks. Qt takes the first family that resolves, so list the techy ones
# first and let it fall back to whatever the OS actually ships.
DISPLAY_FAMILIES = ["Orbitron", "Rajdhani", "Eurostile", "Michroma", "Helvetica Neue", "Arial"]
UI_FAMILIES = ["Rajdhani", "Inter", "SF Pro Display", "Segoe UI", "Helvetica Neue", "Arial"]
MONO_FAMILIES = ["JetBrains Mono", "SF Mono", "Menlo", "Consolas", "DejaVu Sans Mono", "monospace"]


@dataclass(frozen=True)
class Metrics:
    panel_radius: int = 10
    gap: int = 12
    pad: int = 14
    sidebar_width: int = 268
    header_height: int = 74
    footer_height: int = 76


M = Metrics()


def font(size: int, weight: int = 400, family: str = "ui", spacing: float = 0.0):
    """Build a QFont from the stacks above. Imported lazily so theme.py stays
    importable without Qt (the tests do exactly that)."""
    from PySide6.QtGui import QFont

    families = {"display": DISPLAY_FAMILIES, "ui": UI_FAMILIES, "mono": MONO_FAMILIES}[family]
    f = QFont()
    f.setFamilies(families)
    f.setPixelSize(size)
    f.setWeight(QFont.Weight(weight))
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


def rgba(hex_color: str, alpha: float) -> str:
    """'#4FD3FF', 0.2 -> 'rgba(79, 211, 255, 0.2)' for use in stylesheets."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


STYLESHEET = f"""
QWidget {{
    background: transparent;
    color: {C.TEXT};
}}

/* ---- panels ---- */
QFrame#Panel {{
    background: {rgba(C.PANEL, 0.88)};
    border: 1px solid {rgba(C.CYAN, 0.16)};
    border-radius: {M.panel_radius}px;
}}
QFrame#PanelInset {{
    background: {rgba(C.INSET, 0.9)};
    border: 1px solid {rgba(C.CYAN, 0.10)};
    border-radius: 8px;
}}
QLabel#PanelTitle {{
    color: {C.CYAN_DIM};
    font-weight: 700;
}}

/* ---- sidebar navigation ---- */
QPushButton#NavItem {{
    background: transparent;
    border: none;
    border-radius: 8px;
    color: {C.TEXT_MUTED};
    text-align: left;
    padding: 9px 12px;
}}
QPushButton#NavItem:hover {{
    background: {rgba(C.CYAN, 0.07)};
    color: {C.TEXT};
}}
QPushButton#NavItem:checked {{
    background: {rgba(C.CYAN, 0.13)};
    color: {C.CYAN_BRIGHT};
}}

/* ---- generic controls ---- */
QPushButton#Ghost {{
    background: {rgba(C.CYAN, 0.06)};
    border: 1px solid {rgba(C.CYAN, 0.18)};
    border-radius: 8px;
    color: {C.TEXT_MUTED};
    padding: 9px 12px;
    text-align: left;
}}
QPushButton#Ghost:hover {{
    background: {rgba(C.CYAN, 0.14)};
    border-color: {rgba(C.CYAN, 0.42)};
    color: {C.CYAN_BRIGHT};
}}
QPushButton#IconBtn {{
    background: {rgba(C.PANEL_HI, 0.9)};
    border: 1px solid {rgba(C.CYAN, 0.16)};
    border-radius: 8px;
    color: {C.TEXT_MUTED};
}}
QPushButton#IconBtn:hover {{
    border-color: {rgba(C.CYAN, 0.45)};
    color: {C.CYAN_BRIGHT};
}}

QLineEdit#Search {{
    background: {rgba(C.INSET, 0.92)};
    border: 1px solid {rgba(C.CYAN, 0.16)};
    border-radius: 9px;
    color: {C.TEXT};
    padding: 8px 12px;
    selection-background-color: {rgba(C.CYAN, 0.35)};
}}
QLineEdit#Search:focus {{
    border-color: {rgba(C.CYAN, 0.55)};
    background: {rgba(C.INSET, 1.0)};
}}

/* ---- scrollbars: thin, cyan, unobtrusive ---- */
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {rgba(C.CYAN, 0.22)};
    border-radius: 3px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {rgba(C.CYAN, 0.45)}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollArea {{ border: none; }}

QToolTip {{
    background: {C.PANEL_HI};
    color: {C.TEXT};
    border: 1px solid {rgba(C.CYAN, 0.35)};
    padding: 5px 8px;
}}
"""
