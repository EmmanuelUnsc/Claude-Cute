"""Minimum hold: how long an animation must be seen before another replaces it."""

from __future__ import annotations

import time

from .states import IDLE, IDLE_SLEEP, THINKING, ONE_SHOT, WAITING

# Full cycles an animation runs before another may replace it. 0 disables the hold.
MIN_CYCLES = 2

# States that come in immediately, without waiting for the current one to finish.
NO_HOLD = ONE_SHOT | {WAITING}

# States that do not claim screen time: anything else replaces them on arrival.
EPHEMERAL = {IDLE, IDLE_SLEEP, THINKING}


class Smoothing:
    """Tracks how long the current animation has been on screen."""

    def __init__(self, engine) -> None:
        self.engine = engine
        self.shown_since = time.monotonic()

    def mark_shown(self) -> None:
        """Restarts the count. The window calls it when the animation changes."""
        self.shown_since = time.monotonic()

    def can_replace(self, new_state: str) -> bool:
        """Whether the animation on screen has been seen long enough."""
        if new_state in NO_HOLD:
            return True
        return time.monotonic() - self.shown_since >= self.minimum_hold()

    def minimum_hold(self) -> float:
        """Seconds the current state is entitled to occupy the screen."""
        if self.engine.state in EPHEMERAL:
            return 0.0
        duration = self.engine.duration_ms(self.engine.state)
        if duration <= 0:
            return 0.0
        cycles = 1 if self.engine.plays_once() else MIN_CYCLES
        return duration * cycles / 1000.0
