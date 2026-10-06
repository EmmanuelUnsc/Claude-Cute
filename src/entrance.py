"""The entrance: a meteor dives onto the dragon's spot when the widget starts.

Pure arithmetic plus one question to the system, so the shape of the dive is
tested with numbers and the window only has to play it.

The meteor comes in from the upper left along a straight 45 degree line — the
angle its trail is drawn at — and speeds up the whole way, like anything
falling. What happens on impact is a sprite animation (`landing`), not motion.
"""

from __future__ import annotations

import math
import sys

# Pixels per second squared, measured on the vertical. A dive from above a
# 1080 px screen takes about 0.65 s: long enough to see, short enough not to
# make you wait for your own widget.
GRAVITY = 5000.0

# Sideways pixels per pixel of drop. 1.0 is 45 degrees, matching the sprite.
SLANT = 1.0


def fall_ms(distance: float) -> float:
    """How long dropping `distance` pixels takes from rest."""
    return 1000.0 * math.sqrt(2.0 * max(distance, 0.0) / GRAVITY)


def height_at(ms: float, distance: float) -> float:
    """How far above its spot the meteor is, `ms` into the dive.

    `distance` at the start, 0 from impact on. The sideways offset is this
    times `SLANT`.
    """
    seconds = ms / 1000.0
    return max(0.0, distance - 0.5 * GRAVITY * seconds**2)


def animations_enabled() -> bool:
    """Whether the system wants animations at all.

    On Windows this is *Accessibility → Visual effects → Animation effects*.
    Whoever turned that off gets the dragon already in place. Elsewhere there
    is no equally standard setting, so the answer is yes.
    """
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        enabled = wintypes.BOOL(True)
        spi_getclientareaanimation = 0x1042
        ctypes.windll.user32.SystemParametersInfoW(
            spi_getclientareaanimation, 0, ctypes.byref(enabled), 0
        )
        return bool(enabled.value)
    except Exception:  # noqa: BLE001 — when unsure, animate
        return True
