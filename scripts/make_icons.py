#!/usr/bin/env python3
"""Generate FleetBox PWA app icons.

Renders a simple, flat car-on-blue icon (full-bleed so it works as a
``maskable`` icon) in the sizes referenced by the web app manifest, plus an
Apple touch icon and a crisp SVG version for desktop installs.

Run from the repository root:

    python scripts/make_icons.py

Requires Pillow (a dev/build dependency only — the generated PNGs are checked
into the repository, so the running app never needs Pillow).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parent.parent / "app" / "static" / "icons"

BG = (37, 99, 235)  # --primary #2563eb
BODY = (255, 255, 255)
GLASS = (37, 99, 235)
WHEEL = (31, 41, 51)  # #1f2933
LIGHT = (250, 204, 21)  # warm headlight


def _car(draw: ImageDraw.ImageDraw, s: float) -> None:
    """Draw a stylised white car centred on a square of side ``s``."""
    # Roof / cabin (trapezoid).
    draw.polygon(
        [(0.34 * s, 0.48 * s), (0.42 * s, 0.33 * s),
         (0.62 * s, 0.33 * s), (0.70 * s, 0.48 * s)],
        fill=BODY,
    )
    # Side windows (cut into the cabin).
    draw.polygon(
        [(0.405 * s, 0.47 * s), (0.45 * s, 0.37 * s),
         (0.505 * s, 0.37 * s), (0.505 * s, 0.47 * s)],
        fill=GLASS,
    )
    draw.polygon(
        [(0.535 * s, 0.47 * s), (0.535 * s, 0.37 * s),
         (0.60 * s, 0.37 * s), (0.645 * s, 0.47 * s)],
        fill=GLASS,
    )
    # Body.
    draw.rounded_rectangle(
        [(0.17 * s, 0.46 * s), (0.83 * s, 0.64 * s)],
        radius=0.06 * s,
        fill=BODY,
    )
    # Headlights.
    draw.ellipse([(0.78 * s, 0.50 * s), (0.825 * s, 0.545 * s)], fill=LIGHT)
    # Wheels (with a lighter hub).
    for cx in (0.33 * s, 0.67 * s):
        r = 0.085 * s
        draw.ellipse([(cx - r, 0.60 * s), (cx + r, 0.60 * s + 2 * r)], fill=WHEEL)
        draw.ellipse(
            [(cx - 0.035 * s, 0.635 * s), (cx + 0.035 * s, 0.705 * s)],
            fill=BODY,
        )


def render_png(size: int) -> Image.Image:
    # Supersample for smooth edges, then downscale.
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (*BG, 255))
    draw = ImageDraw.Draw(img)
    _car(draw, s)
    return img.resize((size, size), Image.LANCZOS)


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"
     role="img" aria-label="FleetBox">
  <rect width="100" height="100" fill="#2563eb"/>
  <polygon points="34,48 42,33 62,33 70,48" fill="#fff"/>
  <polygon points="40.5,47 45,37 50.5,37 50.5,47" fill="#2563eb"/>
  <polygon points="53.5,47 53.5,37 60,37 64.5,47" fill="#2563eb"/>
  <rect x="17" y="46" width="66" height="18" rx="6" fill="#fff"/>
  <circle cx="80.2" cy="52.2" r="2.2" fill="#facc15"/>
  <circle cx="33" cy="68.5" r="8.5" fill="#1f2933"/>
  <circle cx="67" cy="68.5" r="8.5" fill="#1f2933"/>
  <circle cx="33" cy="68.5" r="3.5" fill="#fff"/>
  <circle cx="67" cy="68.5" r="3.5" fill="#fff"/>
</svg>
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for size, name in [(192, "icon-192.png"), (512, "icon-512.png"),
                       (180, "apple-touch-icon.png")]:
        render_png(size).save(OUT_DIR / name, optimize=True)
        print("wrote", OUT_DIR / name)
    (OUT_DIR / "icon.svg").write_text(SVG, encoding="utf-8")
    print("wrote", OUT_DIR / "icon.svg")


if __name__ == "__main__":
    main()
