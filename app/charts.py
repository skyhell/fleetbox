"""Dependency-free SVG charts.

The functions return SVG markup as a string. They use only SVG presentation
attributes (``fill``, ``stroke``, …) rather than inline ``style`` attributes or
scripts, so they render under FleetBox's strict Content-Security-Policy. The
returned SVG scales to its container via ``viewBox`` + ``width="100%"``.
"""

from __future__ import annotations

from html import escape

# Palette (mirrors the CSS custom properties).
_PRIMARY = "#2563eb"
_AXIS = "#9aa5b1"
_TEXT = "#6b7785"
_GRID = "#e2e7ee"

_W = 720
_H = 260
_PAD_L = 52
_PAD_R = 14
_PAD_T = 14
_PAD_B = 34


def _fmt(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


def _text(x: float, y: float, content: str, *, anchor: str = "middle", size: float = 11) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{_TEXT}" '
        f'text-anchor="{anchor}" font-family="system-ui, sans-serif">{escape(content)}</text>'
    )


def _frame(plot_w: float, plot_h: float, top_value: float, unit: str) -> list[str]:
    """Axes, three gridlines and their y-labels."""
    parts: list[str] = []
    for i in range(3):
        frac = i / 2
        y = _PAD_T + plot_h * (1 - frac)
        parts.append(
            f'<line x1="{_PAD_L}" y1="{y:.1f}" x2="{_PAD_L + plot_w:.1f}" y2="{y:.1f}" '
            f'stroke="{_GRID}" stroke-width="1"/>'
        )
        parts.append(_text(_PAD_L - 6, y + 3, _fmt(top_value * frac), anchor="end"))
    if unit:
        parts.append(_text(_PAD_L - 6, _PAD_T - 2, unit, anchor="end", size=10))
    return parts


def _empty() -> str:
    return ""


def bar_chart(labels: list[str], values: list[float], *, unit: str = "") -> str:
    if not values:
        return _empty()
    plot_w = _W - _PAD_L - _PAD_R
    plot_h = _H - _PAD_T - _PAD_B
    top = max(values) or 1.0

    parts = [f'<svg viewBox="0 0 {_W} {_H}" width="100%" role="img" class="chart">']
    parts += _frame(plot_w, plot_h, top, unit)

    n = len(values)
    slot = plot_w / n
    bar_w = slot * 0.62
    # Label every Nth tick so they don't overlap.
    step = max(1, n // 12)
    for i, (label, value) in enumerate(zip(labels, values, strict=False)):
        h = (value / top) * plot_h
        x = _PAD_L + slot * i + (slot - bar_w) / 2
        y = _PAD_T + plot_h - h
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" '
            f'rx="2" fill="{_PRIMARY}"><title>{escape(label)}: {_fmt(value)}</title></rect>'
        )
        if i % step == 0:
            parts.append(_text(x + bar_w / 2, _H - _PAD_B + 16, label, size=10))
    parts.append("</svg>")
    return "".join(parts)


def line_chart(labels: list[str], values: list[float], *, unit: str = "") -> str:
    if not values:
        return _empty()
    plot_w = _W - _PAD_L - _PAD_R
    plot_h = _H - _PAD_T - _PAD_B
    top = max(values) or 1.0
    bottom = min(values + [0.0])
    span = (top - bottom) or 1.0

    n = len(values)
    step_x = plot_w / max(1, n - 1)

    def point(i: int, value: float) -> tuple[float, float]:
        x = _PAD_L + step_x * i
        y = _PAD_T + plot_h * (1 - (value - bottom) / span)
        return x, y

    parts = [f'<svg viewBox="0 0 {_W} {_H}" width="100%" role="img" class="chart">']
    # Gridlines/labels scaled from bottom..top.
    for i in range(3):
        frac = i / 2
        y = _PAD_T + plot_h * (1 - frac)
        parts.append(
            f'<line x1="{_PAD_L}" y1="{y:.1f}" x2="{_PAD_L + plot_w:.1f}" y2="{y:.1f}" '
            f'stroke="{_GRID}" stroke-width="1"/>'
        )
        parts.append(_text(_PAD_L - 6, y + 3, _fmt(bottom + span * frac), anchor="end"))
    if unit:
        parts.append(_text(_PAD_L - 6, _PAD_T - 2, unit, anchor="end", size=10))

    coords = [point(i, v) for i, v in enumerate(values)]
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    parts.append(
        f'<polyline points="{polyline}" fill="none" stroke="{_PRIMARY}" '
        f'stroke-width="2" stroke-linejoin="round"/>'
    )
    step = max(1, n // 12)
    for i, ((x, y), label, value) in enumerate(zip(coords, labels, values, strict=False)):
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{_PRIMARY}">'
            f'<title>{escape(label)}: {_fmt(value)}</title></circle>'
        )
        if i % step == 0 or i == n - 1:
            parts.append(_text(x, _H - _PAD_B + 16, label, size=10))
    parts.append(f'<line x1="{_PAD_L}" y1="{_PAD_T + plot_h:.1f}" x2="{_PAD_L + plot_w:.1f}" '
                 f'y2="{_PAD_T + plot_h:.1f}" stroke="{_AXIS}" stroke-width="1"/>')
    parts.append("</svg>")
    return "".join(parts)
