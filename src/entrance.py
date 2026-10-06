"""The entrance: the dragon drops onto its spot when the widget starts.

Pure arithmetic plus one question to the system, so the shape of the fall is
tested with numbers and the window only has to play it.

The motion is a real fall — constant gravity, so it starts slow and speeds up —
followed by one short hop on landing. Same gravity for both, which is what
makes the hop read as weight rather than as an effect.
"""

from __future__ import annotations

import math
import sys

# Pixels per second squared. A whole 1080 px screen takes about 0.65 s: long
# enough to see, short enough not to make you wait for your own widget.
GRAVITY = 5000.0

# How high the landing hop goes, as a share of the avatar's side. Relative, so
# a character drawn at another scale bounces in proportion.
HOP_SHARE = 1 / 16


def fall_ms(distance: float) -> float:
    """How long falling `distance` pixels takes from rest."""
    return 1000.0 * math.sqrt(2.0 * max(distance, 0.0) / GRAVITY)


def hop_ms(height: float) -> float:
    """How long a hop `height` pixels high takes, up and back down."""
    return 2.0 * fall_ms(height)


def height_at(ms: float, distance: float, hop: float) -> float:
    """How far above its spot the avatar is, `ms` into the entrance.

    `distance` at the start, 0 on touching down, up to `hop` mid-hop, and 0
    for good once the hop lands.
    """
    seconds = ms / 1000.0
    falling = fall_ms(distance) / 1000.0
    if seconds < falling:
        return distance - 0.5 * GRAVITY * seconds**2
    seconds -= falling
    if seconds < hop_ms(hop) / 1000.0:
        # Thrown up at the speed that reaches exactly `hop`.
        speed = math.sqrt(2.0 * GRAVITY * hop)
        return max(0.0, speed * seconds - 0.5 * GRAVITY * seconds**2)
    return 0.0


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
