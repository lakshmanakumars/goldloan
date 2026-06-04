"""White-label branding helpers.

Turns a single per-tenant brand hex colour into the colour artefacts the
UI needs:

* an Unfold ``primary`` palette (50..950, each as a space-separated
  ``"r g b"`` string, the format Unfold/Tailwind expect), and
* a darker shade of the base for hover/`--vh-primary-dark`.

Used by :func:`apps.core.views.theme_css` to emit a per-tenant stylesheet
and (optionally) by the Unfold ``COLORS`` config.
"""
from __future__ import annotations

# Default brand (Vaarahi orange) — used on the super-admin host and as a
# fallback when a tenant hasn't picked a colour.
DEFAULT_PRIMARY = '#c46616'
DEFAULT_ACCENT = '#f59e0b'

# How far each shade sits from the 600 base. Positive = mix toward white
# (lighter tints), negative = mix toward black (darker shades). Tuned to
# mirror the original hand-built orange ramp.
_RAMP = {
    '50': 0.92, '100': 0.84, '200': 0.68, '300': 0.50,
    '400': 0.30, '500': 0.14, '600': 0.0,
    '700': -0.18, '800': -0.36, '900': -0.52, '950': -0.72,
}


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    """'#c46616' or 'c46616' -> (196, 102, 22). Falls back to the default
    brand colour on anything malformed."""
    v = (value or '').strip().lstrip('#')
    if len(v) == 3:                       # short form #abc
        v = ''.join(ch * 2 for ch in v)
    try:
        return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    except (ValueError, IndexError):
        return hex_to_rgb(DEFAULT_PRIMARY)


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return '#{:02x}{:02x}{:02x}'.format(*rgb)


def _mix(rgb: tuple[int, int, int], target: int, t: float) -> tuple[int, int, int]:
    """Blend ``rgb`` toward ``target`` (0=black or 255=white) by fraction t."""
    return tuple(round(c + (target - c) * t) for c in rgb)  # type: ignore[return-value]


def shade(value: str, t: float) -> str:
    """Return ``value`` lightened (t>0) or darkened (t<0) by |t|, as hex."""
    rgb = hex_to_rgb(value)
    return rgb_to_hex(_mix(rgb, 255 if t >= 0 else 0, abs(t)))


def palette(value: str) -> dict[str, str]:
    """Build a full 50..950 Unfold palette from one base hex.

    Returns ``{'600': '196 102 22', ...}`` — space-separated RGB strings."""
    base = hex_to_rgb(value)
    out: dict[str, str] = {}
    for key, t in _RAMP.items():
        rgb = base if t == 0 else _mix(base, 255 if t > 0 else 0, abs(t))
        out[key] = '{} {} {}'.format(*rgb)
    return out
