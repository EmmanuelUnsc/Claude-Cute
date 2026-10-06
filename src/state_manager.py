"""The live state machine: what each session is doing and what the dragon shows.

This is where the mutable part lives. The table of which states exist, what
inherits from what, how long each lasts and how urgent it is lives in
`states.py`, which is pure data and never changes while the program runs.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
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
    SLEEP,
    START_TURN,
    STATES,
    TRANSIENTS,
    TURN_END_GRACE,
    TURN_SCOPED,
    WAITING,
    priority,
    stall_limit,
    state_for,
)


@dataclass
class _Track:
    """What one session is doing, and what is needed to judge its events.

    The ordering and straggler filters live here, per session: one session's
    old event says nothing about another's new one.
    """

    state: str = IDLE
    changed_at: float = field(default_factory=time.monotonic)
    seen_at: float = field(default_factory=time.monotonic)
    last_ts: float | None = None
    turn_ended_at: float | None = None
    # A session counts once it *does* something, not when it opens: the
    # sessions an editor spawns and drops on startup never count.
    counts: bool = False
    # The Claude Code process behind the session, when the hook found it.
    pid: int | None = None

    def set(self, state: str) -> None:
        # The clock restarts even on the same state: a repeated event is news,
        # and news is what keeps the stall watchdog away.
        self.state = state
        self.changed_at = time.monotonic()

    def reset(self) -> None:
        self.set(IDLE)
        self.last_ts = None
        self.turn_ended_at = None

    def expire(self) -> None:
        """Moves on a transient that ran out, or gives up on a stalled state."""
        elapsed = time.monotonic() - self.changed_at
        duration, next_state = TRANSIENTS.get(self.state, (None, None))
        if duration is not None:
            if elapsed >= duration:
                self.set(next_state)
        elif self.state not in (IDLE, IDLE_SLEEP):
            if elapsed >= stall_limit(self.state):
                self.set(IDLE)


class StateManager:
    """Tracks every session and decides which one the dragon shows.

    Thread-safe: the HTTP server writes from its own thread and the UI reads
    from Qt's.
    """

    def __init__(self, on_change: Callable[[str], None] | None = None) -> None:
        # One track per session, plus the floor: events with no session (curl,
        # an older hook), states forced by hand, and the sleep once everyone
        # has gone. It never leaves and never counts as a session.
        self._sessions: dict[str, _Track] = {}
        self._floor = _Track()
        # A forced state is shown over everything until the next event.
        self._forced = False
        self._state = IDLE
        # When the last session left, and whether any ever showed up. Both
        # are needed: an empty registry looks the same before and after.
        self._ever_seen = False
        self._emptied_at: float | None = None
        self._lock = threading.Lock()
        self._on_change = on_change

    @property
    def state(self) -> str:
        """What the dragon should show right now."""
        with self._lock:
            return self._state

    def set_state(self, state: str) -> str:
        """Shows a state right away, over every session.

        The menu's emergency exit: every session goes back to `idle`, which
        also settles a pending `waiting`, and their ordering is forgotten.
        """
        if state not in SESSION_STATES:
            # `dragged` lands here: it describes what the user is doing, not
            # the session, so it lives in the window and never in the truth.
            known = "unknown" if state not in STATES else "not the session's"
            raise ValueError(f"{known} state: {state!r}")
        with self._lock:
            for track in self._sessions.values():
                track.reset()
            self._floor.reset()
            self._floor.set(state)
            self._forced = True
            changed = self._refresh()
        self._notify(changed)
        return state

    def handle_event(
        self,
        event: str,
        tool_name: str | None = None,
        ts: float | None = None,
        session: str | None = None,
        pid: int | None = None,
    ) -> str:
        """Applies a Claude Code event to its session, and returns what shows.

        Every filter below exists so the avatar never shows something that is
        no longer true:

        `ts` — the instant the hook started, used to drop events that arrive
        out of order *within their session*.

        Turn stragglers — a turn-scoped event arriving after that session's
        `Stop` belongs to the previous turn, not to new activity.

        `pid` — the Claude Code process behind the session, so its death can
        end the session when no `SessionEnd` does.
        """
        # A timestamp from the future is a broken clock, not an ordering
        # claim: the event still applies, only its `when` is dropped.
        if ts is not None and ts > time.time() + CLOCK_SKEW:
            ts = None

        with self._lock:
            if self._forced:
                # Whatever was forced by hand gives way to real news.
                self._forced = False
                self._floor.set(IDLE)

            if session is not None and event == "SessionEnd":
                self._leave(session)
                self._alive()
                changed = self._refresh()
                track = None
            elif session is None:
                track = self._floor
            else:
                track = self._sessions.setdefault(session, _Track())
                track.seen_at = time.monotonic()
                if pid is not None:
                    track.pid = pid
                if event != "SessionStart":
                    track.counts = True
                    self._ever_seen = True

            if track is not None:
                self._alive(keep=session)
                if self._accepts(track, event, ts):
                    self._apply(track, event, state_for(event, tool_name), ts)
                changed = self._refresh()
        self._notify(changed)
        return self.state

    def tick(self) -> str:
        """Call periodically: expires transients and stalled states."""
        with self._lock:
            self._floor.expire()
            for track in self._sessions.values():
                track.expire()
            self._alive()
            changed = self._refresh()
        self._notify(changed)
        return self.state

    def abandoned(self) -> bool:
        """Whether every session is gone and the grace period is spent.

        Reports the fact; what to do about it is the window's call. The clock
        starts when the last session leaves and never at startup, so a widget
        opened by hand never closes on its own. A session waiting on the user
        never goes silent-dead, so a pending question holds it back.
        """
        with self._lock:
            self._alive()  # prunes, and starts the clock if it has to
            if self._emptied_at is None:
                return False
            return time.monotonic() - self._emptied_at >= CLOSE_AFTER

    # --- internals: call with the lock held ---------------------------------

    @staticmethod
    def _accepts(track: _Track, event: str, ts: float | None) -> bool:
        """Whether the event is news for its session, or a leftover."""
        # Did it arrive out of order?
        if ts is not None and track.last_ts is not None and ts < track.last_ts:
            return False
        # Is it a straggler from a turn that already closed?
        if event in TURN_SCOPED and track.turn_ended_at is not None:
            if time.monotonic() - track.turn_ended_at < TURN_END_GRACE:
                return False
        return True

    @staticmethod
    def _apply(track: _Track, event: str, state: str, ts: float | None) -> None:
        track.set(state)
        if ts is not None and (track.last_ts is None or ts > track.last_ts):
            track.last_ts = ts
        if event in START_TURN:
            track.turn_ended_at = None
        elif state in (DONE, ERROR_API):
            track.turn_ended_at = time.monotonic()

    def _leave(self, session: str) -> None:
        """Drops a session; if it was the last one that counted, sleep."""
        track = self._sessions.pop(session, None)
        # Opened and closed having done nothing: its leaving means nothing.
        if track is None or not track.counts:
            return
        if not any(t.counts for t in self._sessions.values()):
            self._floor.set(SLEEP)

    def _alive(self, keep: str | None = None) -> None:
        """Forgets silent sessions and keeps the closing clock up to date.

        The safety net for a `SessionEnd` that never arrives. A session in
        `waiting` is never silent-dead: silence is exactly what waiting on a
        person looks like, and `waiting` has its own eight-hour expiry. `keep`
        spares the session whose event is being handled right now.
        """
        limit = time.monotonic() - SESSION_ALIVE
        for session, track in list(self._sessions.items()):
            if session != keep and track.state != WAITING and track.seen_at < limit:
                self._leave(session)
        # Pruning is also the moment the widget can find out it was left alone.
        if any(t.counts for t in self._sessions.values()):
            self._emptied_at = None
        elif self._ever_seen and self._emptied_at is None:
            self._emptied_at = time.monotonic()

    def _refresh(self) -> str | None:
        """Recomputes what shows. Returns it if it changed, else None."""
        if self._forced:
            shown = self._floor.state
        else:
            tracks = [self._floor, *self._sessions.values()]
            shown = max(
                tracks, key=lambda t: (priority(t.state), t.changed_at)
            ).state
        if shown == self._state:
            return None
        self._state = shown
        return shown

    # --- outside the lock ---------------------------------------------------

    def _notify(self, changed: str | None) -> None:
        if changed is not None and self._on_change:
            self._on_change(changed)
