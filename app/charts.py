"""Dependency-free SVG charts.

The functions return SVG markup as a string. They use only SVG presentation
attributes (``fill``, ``stroke``, …) rather than inline ``style`` attributes or
scripts, so they render under FleetBox's strict Content-Security-Policy. Hover
highlighting is done via classes in the stylesheet. The returned SVG scales to
its container via ``viewBox`` + ``width="100%"``.
"""

from __future__ import annotations

from html import escape

# Palette chosen to read well on both light and dark backgrounds (the charts are
# server-rendered SVG and cannot see the active CSS theme).
_PRIMARY = "#3b82f6"
_AXIS = "#94a3b8"
_TEXT = "#94a3b8"
_GRID = "#94a3b8"

_W = 720
_H = 280
_PAD_L = 56
_PAD_R = 16
_PAD_T = 16
_PAD_B = 56  # room for slanted x-axis labels


def _fmt(value: float) -> str:
    """Format a value for axis/tooltip text, grouping thousands with a space."""
    if value == int(value):
        return f"{int(value):,}".replace(",", " ")  # locale-neutral space grouping
    return f"{value:.1f}"


def _text(x: float, y: float, content: str, *, anchor: str = "middle", size: float = 11) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{_TEXT}" '
        f'text-anchor="{anchor}" font-family="system-ui, sans-serif">{escape(content)}</text>'
    )


def _open(title: str) -> str:
    label = f' aria-label="{escape(title)}"' if title else ""
    inner = f"<title>{escape(title)}</title>" if title else ""
    return f'<svg viewBox="0 0 {_W} {_H}" width="100%" role="img"{label} class="chart">{inner}'


def _y_gridlines(plot_w: float, plot_h: float, bottom: float, span: float, unit: str) -> list[str]:
    parts: list[str] = []
    for i in range(3):
        frac = i / 2
        y = _PAD_T + plot_h * (1 - frac)
        parts.append(
            f'<line x1="{_PAD_L}" y1="{y:.1f}" x2="{_PAD_L + plot_w:.1f}" y2="{y:.1f}" '
            f'stroke="{_GRID}" stroke-width="1" stroke-opacity="0.3"/>'
        )
        parts.append(_text(_PAD_L - 8, y + 3, _fmt(bottom + span * frac), anchor="end"))
    if unit:
        parts.append(_text(_PAD_L - 8, _PAD_T - 4, unit, anchor="end", size=10))
    return parts


def _x_axis(plot_w: float, axis_y: float) -> str:
    return (
        f'<line x1="{_PAD_L}" y1="{axis_y:.1f}" x2="{_PAD_L + plot_w:.1f}" y2="{axis_y:.1f}" '
        f'stroke="{_AXIS}" stroke-width="1"/>'
    )


def _x_labels(positions: list[tuple[float, str]], axis_y: float) -> list[str]:
    """Render x-axis labels, thinned to avoid crowding and slanted when long."""
    n = len(positions)
    if n == 0:
        return []
    step = max(1, n // 12)
    slant = any(len(label) > 5 for _, label in positions)
    parts: list[str] = []
    for i, (cx, label) in enumerate(positions):
        if i % step and i != n - 1:
            continue
        y = axis_y + 14
        if slant:
            parts.append(
                f'<text x="{cx:.1f}" y="{y:.1f}" font-size="10" fill="{_TEXT}" '
                f'text-anchor="end" font-family="system-ui, sans-serif" '
                f'transform="rotate(-40 {cx:.1f} {y:.1f})">{escape(label)}</text>'
            )
        else:
            parts.append(_text(cx, y, label, size=10))
    return parts


def bar_chart(labels: list[str], values: list[float], *, unit: str = "", title: str = "") -> str:
    if not values:
        return ""
    plot_w = _W - _PAD_L - _PAD_R
    plot_h = _H - _PAD_T - _PAD_B
    axis_y = _PAD_T + plot_h
    top = max(values) or 1.0

    parts = [_open(title)]
    parts += _y_gridlines(plot_w, plot_h, 0.0, top, unit)

    n = len(values)
    slot = plot_w / n
    bar_w = slot * 0.62
    positions: list[tuple[float, str]] = []
    for i, (label, value) in enumerate(zip(labels, values, strict=False)):
        h = (value / top) * plot_h
        x = _PAD_L + slot * i + (slot - bar_w) / 2
        y = axis_y - h
        cx = x + bar_w / 2
        positions.append((cx, label))
        parts.append(
            f'<rect class="bar" x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" '
            f'rx="2" fill="{_PRIMARY}"><title>{escape(label)}: {_fmt(value)} {escape(unit)}</title>'
            f"</rect>"
        )
    parts.append(_x_axis(plot_w, axis_y))
    parts += _x_labels(positions, axis_y)
    parts.append("</svg>")
    return "".join(parts)


def line_chart(labels: list[str], values: list[float], *, unit: str = "", title: str = "") -> str:
    if not values:
        return ""
    plot_w = _W - _PAD_L - _PAD_R
    plot_h = _H - _PAD_T - _PAD_B
    axis_y = _PAD_T + plot_h
    top = max(values) or 1.0
    bottom = min(values + [0.0])
    span = (top - bottom) or 1.0

    n = len(values)
    step_x = plot_w / max(1, n - 1)

    coords = [
        (_PAD_L + step_x * i, _PAD_T + plot_h * (1 - (v - bottom) / span))
        for i, v in enumerate(values)
    ]

    parts = [_open(title)]
    parts += _y_gridlines(plot_w, plot_h, bottom, span, unit)

    # Soft area under the line for emphasis.
    area = f"{coords[0][0]:.1f},{axis_y:.1f} "
    area += " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area += f" {coords[-1][0]:.1f},{axis_y:.1f}"
    parts.append(f'<polygon points="{area}" fill="{_PRIMARY}" fill-opacity="0.08"/>')

    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    parts.append(
        f'<polyline points="{polyline}" fill="none" stroke="{_PRIMARY}" '
        f'stroke-width="2" stroke-linejoin="round"/>'
    )

    positions: list[tuple[float, str]] = []
    for (x, y), label, value in zip(coords, labels, values, strict=False):
        positions.append((x, label))
        parts.append(
            f'<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{_PRIMARY}">'
            f'<title>{escape(label)}: {_fmt(value)} {escape(unit)}</title></circle>'
        )
    parts.append(_x_axis(plot_w, axis_y))
    parts += _x_labels(positions, axis_y)
    parts.append("</svg>")
    return "".join(parts)
