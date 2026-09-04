"""The live state machine: what the state is now and who changed it.

This is where the mutable part lives. The table of which states exist, what
inherits from what and how long each lasts is in `states.py`, which is pure
data and never changes while the program runs.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from .states import (
    CLOCK_SKEW,
    CLOSE_AFTER,
    DONE,
    SESSION_STATES,
    ERROR_API,
    IDLE,
    IDLE_SLEEP,
    SESSION_ALIVE,
    SLEEP_AFTER,
    START_TURN,
    STATES,
    TRANSIENTS,
    TURN_END_GRACE,
    TURN_SCOPED,
    WAITING,
    stall_limit,
    state_for,
)


class StateManager:
    """Holds the current state and notifies subscribers when it changes.

    Thread-safe: the HTTP server writes from its own thread and the UI reads
    from Qt's.
    """

    def __init__(self, on_change: Callable[[str], None] | None = None) -> None:
        self._state = IDLE
        self._changed_at = time.monotonic()
        self._last_ts: float | None = None
        self._session: str | None = None
        # Which sessions have shown signs of life, and when.
        self._sessions: dict[str, float] = {}
        # When the last live session left, and whether any ever showed up. Both
        # are needed: an empty registry looks the same before and after.
        self._ever_seen = False
        self._emptied_at: float | None = None
        # Which session left a question unanswered. Nothing overwrites it.
        self._awaiting: str | None = None
        self._turn_ended_at: float | None = None
        self._lock = threading.Lock()
        self._on_change = on_change

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def set_state(self, state: str) -> str:
        """Sets the state directly, skipping the ordering checks."""
        if state not in SESSION_STATES:
            # `dragged` lands here: it describes what the user is doing, not
            # the session, so it lives in the window and never in the truth.
            known = "unknown" if state not in STATES else "not the session's"
            raise ValueError(f"{known} state: {state!r}")
        with self._lock:
            self._last_ts = None
            self._turn_ended_at = None
        return self._apply(state)

    def _alive(self) -> set[str]:
        """Sessions seen recently, forgetting the old ones.

        **Call with the lock held.**
        """
        limit = time.monotonic() - SESSION_ALIVE
        for session in [s for s, seen in self._sessions.items() if seen < limit]:
            del self._sessions[session]
        # Pruning is also the moment the widget can find out it was left alone.
        if self._sessions:
            self._emptied_at = None
        elif self._ever_seen and self._emptied_at is None:
            self._emptied_at = time.monotonic()
        return set(self._sessions)

    def handle_event(
        self,
        event: str,
        tool_name: str | None = None,
        ts: float | None = None,
        session: str | None = None,
    ) -> str:
        """Applies the state matching a Claude Code event.

        Every filter below exists so the avatar never shows something that is
        no longer true:

        `session` — hooks are global, so every Claude Code session writes to
        this same widget. The one that opened the last turn is in charge.

        `ts` — the instant the hook started, used to drop events that arrive
        out of order.

        Turn stragglers — a turn-scoped event arriving after the `Stop` belongs
        to the previous turn, not to new activity.
        """
        # A timestamp from the future is a broken clock, not an ordering
        # claim: the event still applies, only its `when` is dropped.
        if ts is not None and ts > time.time() + CLOCK_SKEW:
            ts = None

        # A session counts once it *does* something, not when it opens: the
        # sessions an editor spawns and drops on startup never register.
        ghost = False
        with self._lock:
            if session is not None:
                if event == "SessionEnd":
                    # Whoever left cannot stay in charge of the widget.
                    if self._session == session:
                        self._session = None
                    if session in self._sessions:
                        self._sessions.pop(session, None)
                        if self._awaiting == session:
                            self._awaiting = None
                    else:
                        # Opened and closed having done nothing: its leaving
                        # means nothing either.
                        ghost = True
                elif event != "SessionStart":
                    self._ever_seen = True
                    self._sessions[session] = time.monotonic()
            alive = self._alive()
            active_session = self._session
            turn_ended_at = self._turn_ended_at
            last_ts = self._last_ts
            awaiting = self._awaiting

        if ghost:
            return self.state

        # 0. Another session left a question unanswered: do not overwrite it,
        #    unless that session is gone.
        if session is not None and awaiting is not None and awaiting != session:
            if awaiting in alive:
                return self.state
            with self._lock:
                if self._awaiting == awaiting:
                    self._awaiting = None

        # 1. A session ended while others are alive: closing one window is
        #    not "everything is over".
        if event == "SessionEnd" and session is not None and alive:
            return self.state

        # 2. Which session is this from?
        if session is not None:
            if event in START_TURN:
                active_session = session  # claims the widget
            elif active_session is not None and session != active_session:
                return self.state  # another session: not in charge here

        # 3. Did it arrive out of order?
        if ts is not None and last_ts is not None and ts < last_ts:
            return self.state

        # 4. Is it a straggler from a turn that already closed?
        if event in TURN_SCOPED and turn_ended_at is not None:
            if time.monotonic() - turn_ended_at < TURN_END_GRACE:
                return self.state

        state = self._apply(state_for(event, tool_name))

        with self._lock:
            if session is not None:
                self._session = active_session
                if state == WAITING:
                    self._awaiting = session
            if ts is not None and (self._last_ts is None or ts > self._last_ts):
                self._last_ts = ts
            if event in START_TURN:
                self._turn_ended_at = None
            elif state in (DONE, ERROR_API):
                self._turn_ended_at = time.monotonic()

        return state

    def abandoned(self) -> bool:
        """Whether every session is gone and the grace period is spent.

        Reports the fact; what to do about it is the window's call. The clock
        starts when the last session leaves and never at startup, so a widget
        opened by hand never closes on its own. A pending `waiting` holds it
        back, and `SESSION_ALIVE` covers a `SessionEnd` that never arrived.
        """
        with self._lock:
            if self._awaiting is not None:
                return False
            self._alive()  # prunes, and starts the clock if it has to
            if self._emptied_at is None:
                return False
            return time.monotonic() - self._emptied_at >= CLOSE_AFTER

    def tick(self) -> str:
        """Call periodically: expires the transient states."""
        with self._lock:
            current = self._state
            elapsed = time.monotonic() - self._changed_at

        duration, next_state = TRANSIENTS.get(current, (None, None))
        if duration is not None and elapsed >= duration:
            return self._apply(next_state)

        if current == IDLE and elapsed >= SLEEP_AFTER:
            return self._apply(IDLE_SLEEP)

        # No active state may stay stuck forever.
        if current not in (IDLE, IDLE_SLEEP) and elapsed >= stall_limit(current):
            return self._apply(IDLE)

        return current

    def _apply(self, state: str) -> str:
        with self._lock:
            changed = state != self._state
            self._state = state
            self._changed_at = time.monotonic()
            # Leaving `waiting` settles the debt, however it happens.
            if state != WAITING:
                self._awaiting = None
        if changed and self._on_change:
            self._on_change(state)
        return state
