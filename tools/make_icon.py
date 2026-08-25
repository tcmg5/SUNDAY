#!/usr/bin/env python3
"""Generate assets/jarvis.ico (and a PNG) - the arc reactor, at icon scale.

Regenerate with:  python tools/make_icon.py

Drawn at 4x and downsampled, because Windows renders the 16px variant in the
taskbar and thin cyan rings alias badly without supersampling.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SIZES = [16, 24, 32, 48, 64, 128, 256]

BG_OUTER = (4, 10, 18)
BG_INNER = (10, 32, 48)
CYAN = (79, 211, 255)
CYAN_BRIGHT = (170, 240, 255)


def draw(size: int) -> Image.Image:
    s = size * 4  # supersample
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = s / 2

    # Rounded-square body with a soft radial fill.
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=s * 0.22, fill=BG_OUTER)
    for i in range(int(s * 0.42), 0, -1):
        t = i / (s * 0.42)
        colour = tuple(int(BG_OUTER[j] + (BG_INNER[j] - BG_OUTER[j]) * (1 - t)) for j in range(3))
        d.ellipse([c - i, c - i, c + i, c + i], fill=colour)

    # Outer ring
    d.ellipse([c - s * 0.36, c - s * 0.36, c + s * 0.36, c + s * 0.36],
              outline=CYAN + (200,), width=max(2, int(s * 0.022)))

    # Three arc segments, the arc-reactor signature
    box = [c - s * 0.28, c - s * 0.28, c + s * 0.28, c + s * 0.28]
    for start in (20, 140, 260):
        d.arc(box, start, start + 76, fill=CYAN + (255,), width=max(2, int(s * 0.030)))

    # Tick marks
    for i in range(24):
        angle = math.radians(i * 15)
        r0, r1 = s * 0.175, s * 0.205
        d.line(
            [c + math.cos(angle) * r0, c + math.sin(angle) * r0,
             c + math.cos(angle) * r1, c + math.sin(angle) * r1],
            fill=CYAN + (130,), width=max(1, int(s * 0.008)),
        )

    # Glowing core
    for i in range(int(s * 0.15), 0, -1):
        t = i / (s * 0.15)
        colour = tuple(int(CYAN_BRIGHT[j] * (1 - t) + CYAN[j] * t) for j in range(3))
        d.ellipse([c - i, c - i, c + i, c + i], fill=colour + (255,))

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    frames = [draw(size) for size in SIZES]
    ico = ASSETS / "jarvis.ico"
    frames[-1].save(ico, format="ICO", sizes=[(s, s) for s in SIZES])
    frames[-1].save(ASSETS / "jarvis.png", format="PNG")
    print(f"wrote {ico} ({', '.join(str(s) for s in SIZES)} px) and jarvis.png")


if __name__ == "__main__":
    main()
