"""Tests for the state machine.

`state_manager` is plain Python, no Qt: tested without starting an interface.
The table it consults is tested separately, in `test_states.py`.

Several tests here swap a real table for a test one so they do not have to wait
out real seconds. Each is patched **in the module that reads it**: `tick()`
looks at `TRANSIENTS` and `SESSION_ALIVE` in `state_manager`'s namespace, while
`stall_limit()` looks at `STALL_AFTER` in `states`'.
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import states as st
from src import state_manager as sm
from src.states import state_for
from src.state_manager import StateManager


class TestStateManager(unittest.TestCase):
    def test_it_starts_in_idle(self):
        self.assertEqual(StateManager().state, st.IDLE)

    def test_a_valid_set_state(self):
        m = StateManager()
        self.assertEqual(m.set_state(st.WAITING), st.WAITING)
        self.assertEqual(m.state, st.WAITING)

    def test_an_invalid_set_state_raises(self):
        with self.assertRaises(ValueError):
            StateManager().set_state("does-not-exist")

    def test_every_session_state_is_assignable(self):
        m = StateManager()
        for state in st.SESSION_STATES:
            self.assertEqual(m.set_state(state), state)

    def test_the_manager_refuses_what_the_session_does_not_produce(self):
        # `dragged` is declared, drawable and forceable on screen, but it says
        # what the user is doing. In the truth it would make `/state` lie about
        # Claude and would hand the expiry watchdog something that ends when
        # you let go of the mouse.
        with self.assertRaises(ValueError):
            StateManager().set_state(st.DRAGGED)

    def test_session_states_are_the_whole_tree_minus_the_window_ones(self):
        # Guards the derivation: a state added to the tree is a session state
        # unless someone deliberately says otherwise.
        self.assertEqual(set(st.STATES) - set(st.SESSION_STATES),
                         {st.DRAGGED, st.FALLING})

    def test_the_manager_refuses_the_entrance_too(self):
        with self.assertRaises(ValueError):
            StateManager().set_state(st.FALLING)

    def test_the_callback_only_fires_on_real_changes(self):
        seen = []
        m = StateManager(on_change=seen.append)
        m.set_state(st.THINKING)
        m.set_state(st.THINKING)  # repeated: must not notify
        m.set_state(st.WORKING)
        self.assertEqual(seen, [st.THINKING, st.WORKING])

    def test_a_full_session_flow(self):
        m = StateManager()
        self.assertEqual(m.handle_event("SessionStart"), st.WAKE)
        self.assertEqual(m.handle_event("UserPromptSubmit"), st.THINKING)
        self.assertEqual(m.handle_event("PreToolUse", "Bash"), st.WORKING_BASH)
        self.assertEqual(m.handle_event("PostToolUse"), st.THINKING)
        self.assertEqual(m.handle_event("PreToolUse", "Edit"), st.WORKING_EDIT)
        self.assertEqual(m.handle_event("Stop"), st.DONE)


class TestTransients(unittest.TestCase):
    def setUp(self):
        # The real values are saved so other tests are not contaminated.
        self._transients = dict(sm.TRANSIENTS)

    def tearDown(self):
        sm.TRANSIENTS = self._transients

    def test_done_expires_into_idle(self):
        sm.TRANSIENTS = {st.DONE: (0.05, st.IDLE)}
        m = StateManager()
        m.set_state(st.DONE)
        self.assertEqual(m.tick(), st.DONE)  # not yet
        time.sleep(0.08)
        self.assertEqual(m.tick(), st.IDLE)

    def test_sleep_expires_into_idle_sleep(self):
        sm.TRANSIENTS = {st.SLEEP: (0.05, st.IDLE_SLEEP)}
        m = StateManager()
        m.set_state(st.SLEEP)
        time.sleep(0.08)
        self.assertEqual(m.tick(), st.IDLE_SLEEP)

    def test_a_non_transient_state_does_not_expire(self):
        m = StateManager()
        m.set_state(st.THINKING)
        time.sleep(0.05)
        self.assertEqual(m.tick(), st.THINKING)

    def test_a_long_idle_stays_awake(self):
        # It used to fall asleep after five minutes of `idle`. Now it sleeps
        # only once every session is gone: an open session that is just quiet
        # (you reading code) keeps it awake however long it lasts.
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1, session="A")
        m.handle_event("Stop", ts=2, session="A")
        for track in (m._floor, *m._sessions.values()):
            track.changed_at -= 3600
        self.assertEqual(m.tick(), st.IDLE)


class TestEventOrder(unittest.TestCase):
    """Hooks are separate processes and their POSTs can arrive out of order."""

    def test_an_old_event_does_not_overwrite_a_newer_one(self):
        # The real case: a slow PostToolUse lands after the Stop.
        m = StateManager()
        m.handle_event("Stop", ts=100.0)
        self.assertEqual(m.state, st.DONE)
        m.handle_event("PostToolUse", ts=99.0)  # fired earlier, arrived later
        self.assertEqual(m.state, st.DONE, "an old event overwrote a newer one")

    def test_a_late_pretooluse_does_not_leave_the_fire_stuck(self):
        m = StateManager()
        m.handle_event("Stop", ts=100.0)
        m.handle_event("PreToolUse", "Bash", ts=99.5)
        self.assertEqual(m.state, st.DONE)

    def test_a_newer_event_does_apply(self):
        m = StateManager()
        m.handle_event("Stop", ts=100.0)
        m.handle_event("UserPromptSubmit", ts=101.0)
        self.assertEqual(m.state, st.THINKING)

    def test_without_a_timestamp_it_applies_anyway(self):
        # Compatibility with an older hook that sends no ts. A non-turn event
        # is used so it does not collide with the straggler filter.
        m = StateManager()
        m.handle_event("Stop", ts=100.0)
        m.handle_event("UserPromptSubmit")
        self.assertEqual(m.state, st.THINKING)

    def test_forcing_a_state_always_wins(self):
        # The context menu must not be blocked by the ordering.
        m = StateManager()
        m.handle_event("Stop", ts=1e12)
        m.set_state(st.WORKING)
        self.assertEqual(m.state, st.WORKING)
        m.handle_event("PostToolUse", ts=10.0)
        self.assertEqual(m.state, st.THINKING)

    def test_a_normal_ordered_sequence(self):
        m = StateManager()
        for i, (event, tool, expected) in enumerate([
            ("SessionStart", None, st.WAKE),
            ("UserPromptSubmit", None, st.THINKING),
            ("PreToolUse", "Bash", st.WORKING_BASH),
            ("PostToolUse", "Bash", st.THINKING),
            ("Stop", None, st.DONE),
        ]):
            self.assertEqual(m.handle_event(event, tool, ts=float(i)), expected)


class TestTurnStragglers(unittest.TestCase):
    """A turn event arriving after the Stop is a leftover."""

    def test_a_late_subagentstop_does_not_revive_the_work(self):
        # The real captured case: SubagentStop 4 s after the Stop.
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1.0, session="s1")
        m.handle_event("Stop", ts=2.0, session="s1")
        self.assertEqual(m.state, st.DONE)
        m.handle_event("SubagentStop", ts=3.0, session="s1")
        self.assertEqual(m.state, st.DONE, "a straggler revived the turn")

    def test_a_late_pretooluse_does_not_either(self):
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1.0, session="s1")
        m.handle_event("Stop", ts=2.0, session="s1")
        m.handle_event("PreToolUse", "Bash", ts=3.0, session="s1")
        self.assertEqual(m.state, st.DONE)

    def test_a_new_turn_reopens_everything(self):
        m = StateManager()
        m.handle_event("Stop", ts=1.0, session="s1")
        m.handle_event("UserPromptSubmit", ts=2.0, session="s1")
        self.assertEqual(m.state, st.THINKING)
        self.assertEqual(
            m.handle_event("PreToolUse", "Bash", ts=3.0, session="s1"),
            st.WORKING_BASH,
        )

    def test_the_grace_period_expires(self):
        original = sm.TURN_END_GRACE
        try:
            sm.TURN_END_GRACE = 0.05
            m = StateManager()
            m.handle_event("Stop", ts=1.0, session="s1")
            time.sleep(0.08)
            m.handle_event("PreToolUse", "Bash", ts=2.0, session="s1")
            self.assertEqual(m.state, st.WORKING_BASH)
        finally:
            sm.TURN_END_GRACE = original

    def test_attention_events_are_never_filtered(self):
        # Claude asking for permission always matters, even after the turn
        # closed.
        m = StateManager()
        m.handle_event("Stop", ts=1.0, session="s1")
        m.handle_event("PermissionRequest", ts=2.0, session="s1")
        self.assertEqual(m.state, st.WAITING)

    def test_subagentstop_is_no_longer_work(self):
        self.assertEqual(state_for("SubagentStop"), st.THINKING)


class TestSessions(unittest.TestCase):
    """Hooks are global: every session writes to this same widget."""

    def test_another_session_is_not_in_charge(self):
        # The real captured case: another project's SessionEnd put the dragon
        # to sleep in the middle of this work.
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1.0, session="this-project")
        m.handle_event("PreToolUse", "Bash", ts=2.0, session="this-project")
        self.assertEqual(m.state, st.WORKING_BASH)
        m.handle_event("SessionEnd", ts=3.0, session="other-project")
        self.assertEqual(m.state, st.WORKING_BASH, "another session butted in")

    def test_another_session_claims_it_by_opening_a_turn(self):
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1.0, session="one")
        m.handle_event("UserPromptSubmit", ts=2.0, session="two")
        self.assertEqual(m.state, st.THINKING)
        self.assertEqual(
            m.handle_event("PreToolUse", "Bash", ts=3.0, session="two"),
            st.WORKING_BASH,
        )
        # And now the first one is the one not in charge.
        m.handle_event("SessionEnd", ts=4.0, session="one")
        self.assertEqual(m.state, st.WORKING_BASH)

    def test_without_a_session_it_is_accepted_anyway(self):
        # Compatibility with an older hook, or with curl testing.
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1.0, session="s1")
        self.assertEqual(m.handle_event("Stop", ts=2.0), st.DONE)

    def test_forcing_a_state_clears_the_turn_end(self):
        m = StateManager()
        m.handle_event("Stop", ts=1.0, session="s1")
        m.set_state(st.IDLE)
        self.assertEqual(
            m.handle_event("PreToolUse", "Bash", ts=2.0, session="s1"),
            st.WORKING_BASH,
        )


class TestSeveralSessions(unittest.TestCase):
    """Hooks are global: every session writes to this same widget.

    The two rules tested here came out of measuring. The stolen notice was
    found by reasoning; the ill-timed sleep showed up in the telemetry: 31 of
    the 45 times the avatar fell asleep it was a `SessionEnd`, and in 25 of
    those 45 it went back to work in under ten minutes.
    """

    def setUp(self):
        self._alive = sm.SESSION_ALIVE

    def tearDown(self):
        sm.SESSION_ALIVE = self._alive

    # --- a pending notice is a debt, not a state ---------------------------

    def test_another_session_does_not_steal_a_waiting(self):
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1, session="A")
        m.handle_event("Notification", ts=2, session="A")
        m.handle_event("SessionStart", ts=3, session="B")
        m.handle_event("PreToolUse", "Bash", ts=4, session="B")
        self.assertEqual(m.state, st.WAITING, "another session overwrote it")

    def test_the_owner_of_the_notice_resolves_it(self):
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1, session="A")
        m.handle_event("Notification", ts=2, session="A")
        self.assertEqual(m.handle_event("PostToolUse", ts=3, session="A"),
                         st.THINKING)

    def test_silence_alone_does_not_release_the_notice(self):
        # Silence is exactly what waiting on a person looks like. A session
        # that merely opens is not one that needs the dragon.
        sm.SESSION_ALIVE = 0.0
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1, session="A")
        m.handle_event("Notification", ts=2, session="A")
        self.assertEqual(m.handle_event("SessionStart", ts=3, session="B"),
                         st.WAITING)

    def test_an_abandoned_question_gives_way_to_real_work(self):
        # If the notice's owner stops showing signs of life and nobody can
        # vouch for its process, it cannot block everyone else for 8 hours.
        sm.SESSION_ALIVE = 0.0
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1, session="A")
        m.handle_event("Notification", ts=2, session="A")
        self.assertEqual(
            m.handle_event("PreToolUse", "Bash", ts=3, session="B"),
            st.WORKING_BASH,
        )

    def test_closing_the_session_releases_the_notice(self):
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1, session="A")
        m.handle_event("Notification", ts=2, session="A")
        m.handle_event("UserPromptSubmit", ts=3, session="B")
        self.assertEqual(m.handle_event("SessionEnd", ts=4, session="A"),
                         st.THINKING)

    def test_expiring_the_notice_releases_it(self):
        # The watchdog took it back to idle: the debt no longer exists.
        #
        # Both tables are patched in `states`, which is where `stall_limit()`
        # reads them. Patching them in `state_manager` would have no effect.
        after, default = dict(st.STALL_AFTER), st.STALL_DEFAULT
        st.STALL_AFTER = {}
        st.STALL_DEFAULT = 0.05
        try:
            m = StateManager()
            m.handle_event("UserPromptSubmit", ts=1, session="A")
            m.handle_event("Notification", ts=2, session="A")
            time.sleep(0.08)
            self.assertEqual(m.tick(), st.IDLE, "the watchdog did not expire it")
            self.assertEqual(m.handle_event("SessionStart", ts=3, session="B"),
                             st.WAKE)
        finally:
            st.STALL_AFTER = after
            st.STALL_DEFAULT = default

    def test_forcing_from_the_menu_releases_the_notice(self):
        # The menu always wins: it is the user's emergency exit.
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1, session="A")
        m.handle_event("Notification", ts=2, session="A")
        m.set_state(st.IDLE)
        self.assertEqual(m.handle_event("SessionStart", ts=3, session="B"),
                         st.WAKE)

    # --- closing one window is not "everything is over" --------------------

    def test_it_does_not_sleep_while_another_session_is_alive(self):
        m = StateManager()
        m.handle_event("SessionStart", ts=1, session="A")
        m.handle_event("SessionStart", ts=2, session="B")
        m.handle_event("PreToolUse", "Bash", ts=3, session="B")
        m.handle_event("SessionEnd", ts=4, session="A")
        self.assertEqual(m.state, st.WORKING_BASH, "it slept with B working")

    def test_it_sleeps_when_the_last_one_leaves(self):
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1, session="A")
        m.handle_event("UserPromptSubmit", ts=2, session="B")
        m.handle_event("SessionEnd", ts=3, session="A")
        self.assertEqual(m.handle_event("SessionEnd", ts=4, session="B"),
                         st.SLEEP)

    def test_a_lone_session_still_sleeps_on_close(self):
        # The ordinary case: it opened, it worked, it left.
        m = StateManager()
        m.handle_event("SessionStart", ts=1, session="A")
        m.handle_event("UserPromptSubmit", ts=2, session="A")
        self.assertEqual(m.handle_event("SessionEnd", ts=3, session="A"),
                         st.SLEEP)

    def test_a_session_that_did_nothing_leaves_without_a_trace(self):
        """Regression: the desktop app opens four of these on every start.

        Measured on 02/09 — four sessions born and gone inside a second,
        labelled exactly like a real goodbye. Counting them emptied the
        registry and started the closing clock, and the avatar disappeared
        five minutes into the day.
        """
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1, session="mine")
        m.handle_event("SessionStart", ts=2, session="ghost")
        self.assertNotEqual(
            m.handle_event("SessionEnd", ts=3, session="ghost"), st.SLEEP,
            "a session that did nothing put the avatar to sleep")

    def test_a_session_that_left_stops_being_in_charge(self):
        # Otherwise the one that opened the last turn keeps owning the widget
        # after closing, and everyone else's events are dropped until they
        # open a turn of their own. The ghosts of the app start did exactly
        # that: they claimed it on the way in and never released it.
        m = StateManager()
        m.handle_event("SessionStart", ts=1, session="ghost")
        m.handle_event("SessionEnd", ts=2, session="ghost")
        self.assertEqual(
            m.handle_event("PreToolUse", "Bash", ts=3, session="mine"),
            st.WORKING_BASH, "a session that had left was still in charge")

    def test_dead_sessions_do_not_pile_up(self):
        # The registry must not grow one entry per session that ever existed.
        sm.SESSION_ALIVE = 0.0
        m = StateManager()
        for i in range(20):
            m.handle_event("UserPromptSubmit", ts=i, session=f"S{i}")
        self.assertLessEqual(len(m._sessions), 1)


class TestTheMostUrgentSessionShows(unittest.TestCase):
    """Every session keeps its own state; the dragon shows the most urgent.

    Before this, the last event won, so a session that was merely working
    hid one that had just failed or finished.
    """

    def setUp(self):
        self._transients = dict(sm.TRANSIENTS)
        self._alive = sm.SESSION_ALIVE

    def tearDown(self):
        sm.TRANSIENTS = self._transients
        sm.SESSION_ALIVE = self._alive

    def test_a_question_beats_work(self):
        m = StateManager()
        m.handle_event("PreToolUse", "Bash", ts=1, session="A")
        self.assertEqual(m.handle_event("Notification", ts=2, session="B"),
                         st.WAITING)
        # And work does not take it back while the question stands.
        self.assertEqual(m.handle_event("PreToolUse", "Edit", ts=3, session="A"),
                         st.WAITING)

    def test_answering_gives_the_dragon_back_to_the_rest(self):
        m = StateManager()
        m.handle_event("PreToolUse", "Bash", ts=1, session="A")
        m.handle_event("PermissionRequest", ts=2, session="B")
        self.assertEqual(m.handle_event("PostToolUse", ts=3, session="B"),
                         st.WORKING_BASH)

    def test_another_session_finishing_shows_briefly(self):
        sm.TRANSIENTS = {st.DONE: (0.05, st.IDLE)}
        m = StateManager()
        m.handle_event("PreToolUse", "Bash", ts=1, session="A")
        self.assertEqual(m.handle_event("Stop", ts=2, session="B"), st.DONE)
        time.sleep(0.08)
        self.assertEqual(m.tick(), st.WORKING_BASH)

    def test_opening_a_session_does_not_interrupt_work(self):
        m = StateManager()
        m.handle_event("PreToolUse", "Bash", ts=1, session="A")
        self.assertEqual(m.handle_event("SessionStart", ts=2, session="B"),
                         st.WORKING_BASH)

    def test_a_tie_goes_to_the_latest(self):
        m = StateManager()
        m.handle_event("PreToolUse", "Bash", ts=1, session="A")
        self.assertEqual(m.handle_event("PreToolUse", "Edit", ts=2, session="B"),
                         st.WORKING_EDIT)
        self.assertEqual(m.handle_event("PreToolUse", "Read", ts=3, session="A"),
                         st.WORKING_READ)

    def test_ordering_is_judged_per_session(self):
        # One session's clock says nothing about another's events: a global
        # ordering dropped B's real work as "older" than A's Stop.
        m = StateManager()
        m.handle_event("Stop", ts=100.0, session="A")
        m.handle_event("PreToolUse", "Bash", ts=50.0, session="B")
        # A's `done` outranks it on screen; what matters is that B took it.
        self.assertEqual(m._sessions["B"].state, st.WORKING_BASH)

    def test_stragglers_are_judged_per_session(self):
        # A's turn ending does not make B's tools leftovers.
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1, session="B")
        m.handle_event("Stop", ts=2, session="A")
        m.handle_event("PreToolUse", "Bash", ts=3, session="B")
        self.assertEqual(m._sessions["B"].state, st.WORKING_BASH)

    def test_a_session_still_open_keeps_it_awake(self):
        # B opened and has not done anything yet, but it is there: the last
        # working session leaving is not everyone leaving.
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1, session="A")
        m.handle_event("SessionStart", ts=2, session="B")
        self.assertNotIn(m.handle_event("SessionEnd", ts=3, session="A"),
                         (st.SLEEP, st.IDLE_SLEEP))

    def test_silence_puts_it_to_sleep(self):
        # The net for a `SessionEnd` that never arrives.
        sm.SESSION_ALIVE = 0.0
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1, session="A")
        self.assertEqual(m.tick(), st.SLEEP)

    def test_a_forced_state_gives_way_to_the_next_event(self):
        # Forcing `waiting` from the menu must not leave an eight-hour question
        # sitting on top of every real session.
        m = StateManager()
        m.set_state(st.WAITING)
        self.assertEqual(
            m.handle_event("PreToolUse", "Bash", ts=1, session="A"),
            st.WORKING_BASH,
        )


class FakeProcesses:
    """Stands in for `ProcessWatch`: each pid answers what the test says."""

    def __init__(self):
        self.status: dict[int, bool | None] = {}
        self.forgotten: list[int] = []

    def alive(self, pid):
        return self.status.get(pid, True)

    def forget(self, pid):
        self.forgotten.append(pid)


class TestTheProcessBehindASession(unittest.TestCase):
    """A session ends when its process does, `SessionEnd` or not."""

    def setUp(self):
        self._alive = sm.SESSION_ALIVE
        self.processes = FakeProcesses()

    def tearDown(self):
        sm.SESSION_ALIVE = self._alive

    def manager(self) -> StateManager:
        return StateManager(processes=self.processes)

    def test_the_pid_is_kept_on_the_session(self):
        m = self.manager()
        m.handle_event("UserPromptSubmit", ts=1, session="A", pid=4242)
        self.assertEqual(m._sessions["A"].pid, 4242)

    def test_an_event_without_one_does_not_forget_it(self):
        # A hook that failed to find the process this time says nothing new.
        m = self.manager()
        m.handle_event("UserPromptSubmit", ts=1, session="A", pid=4242)
        m.handle_event("PreToolUse", "Bash", ts=2, session="A")
        self.assertEqual(m._sessions["A"].pid, 4242)

    def test_closing_the_terminal_puts_it_to_sleep(self):
        # The case this exists for: no `SessionEnd`, just a dead process.
        m = self.manager()
        m.handle_event("PreToolUse", "Bash", ts=1, session="A", pid=4242)
        self.processes.status[4242] = False
        self.assertEqual(m.tick(), st.SLEEP)
        self.assertNotIn("A", m._sessions)

    def test_one_terminal_closing_leaves_the_others(self):
        m = self.manager()
        m.handle_event("PreToolUse", "Bash", ts=1, session="A", pid=1)
        m.handle_event("PreToolUse", "Edit", ts=2, session="B", pid=2)
        self.processes.status[2] = False
        self.assertEqual(m.tick(), st.WORKING_BASH)

    def test_a_dead_process_takes_its_question_with_it(self):
        # Nobody is left to answer it, unlike a merely silent session.
        m = self.manager()
        m.handle_event("UserPromptSubmit", ts=1, session="A", pid=1)
        m.handle_event("PreToolUse", "Bash", ts=2, session="B", pid=2)
        m.handle_event("Notification", ts=3, session="A")
        self.processes.status[1] = False
        self.assertEqual(m.tick(), st.WORKING_BASH)

    def test_a_live_process_outlasts_any_silence(self):
        # You reading code for an hour, terminal open: not over.
        sm.SESSION_ALIVE = 0.0
        m = self.manager()
        m.handle_event("UserPromptSubmit", ts=1, session="A", pid=4242)
        m.handle_event("Stop", ts=2, session="A")
        self.assertNotIn(m.tick(), (st.SLEEP, st.IDLE_SLEEP))
        self.assertFalse(m.abandoned())

    def test_a_live_process_keeps_its_question_over_other_work(self):
        # Its terminal is still open, so someone may still answer it.
        sm.SESSION_ALIVE = 0.0
        m = self.manager()
        m.handle_event("UserPromptSubmit", ts=1, session="A", pid=1)
        m.handle_event("Notification", ts=2, session="A")
        self.assertEqual(
            m.handle_event("PreToolUse", "Bash", ts=3, session="B", pid=2),
            st.WAITING,
        )

    def test_when_the_system_will_not_say_silence_decides(self):
        sm.SESSION_ALIVE = 0.0
        m = self.manager()
        m.handle_event("UserPromptSubmit", ts=1, session="A", pid=4242)
        self.processes.status[4242] = None
        self.assertEqual(m.tick(), st.SLEEP)

    def test_a_dead_process_starts_the_closing_clock(self):
        original = sm.CLOSE_AFTER
        sm.CLOSE_AFTER = 0.0
        try:
            m = self.manager()
            m.handle_event("UserPromptSubmit", ts=1, session="A", pid=4242)
            self.processes.status[4242] = False
            self.assertTrue(m.abandoned())
        finally:
            sm.CLOSE_AFTER = original

    def test_leaving_lets_go_of_the_process(self):
        # On Windows that closes the handle that pins the pid.
        m = self.manager()
        m.handle_event("UserPromptSubmit", ts=1, session="A", pid=4242)
        m.handle_event("SessionEnd", ts=2, session="A")
        self.assertEqual(self.processes.forgotten, [4242])

    def test_without_a_watcher_nothing_changes(self):
        # Silence alone, as before: what a manager built with no watcher does.
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1, session="A", pid=4242)
        self.assertEqual(m.tick(), st.THINKING)


class TestNothingGetsStuck(unittest.TestCase):
    """No active state should be able to stay forever."""

    def setUp(self):
        self._stall = dict(st.STALL_AFTER)
        self._default = st.STALL_DEFAULT

    def tearDown(self):
        st.STALL_AFTER = self._stall
        st.STALL_DEFAULT = self._default

    def test_any_active_state_goes_back_to_idle(self):
        st.STALL_AFTER = {}
        st.STALL_DEFAULT = 0.05
        for state in (st.WORKING, st.WORKING_BASH, st.THINKING, st.WAITING,
                      st.COMPACTING):
            m = StateManager()
            m.set_state(state)
            time.sleep(0.08)
            self.assertEqual(m.tick(), st.IDLE, f"{state} got stuck")

    def test_idle_does_not_reset_itself(self):
        # idle is where the watchdog sends things; it never restarts itself.
        st.STALL_AFTER = {}
        st.STALL_DEFAULT = 0.05
        m = StateManager()
        time.sleep(0.08)
        self.assertEqual(m.tick(), st.IDLE)

    def test_idle_sleep_is_stable(self):
        st.STALL_AFTER = {}
        st.STALL_DEFAULT = 0.05
        m = StateManager()
        m.set_state(st.IDLE_SLEEP)
        time.sleep(0.08)
        self.assertEqual(m.tick(), st.IDLE_SLEEP)

    def test_an_event_restarts_the_count(self):
        st.STALL_AFTER = {}
        st.STALL_DEFAULT = 0.2
        m = StateManager()
        m.set_state(st.WORKING)
        time.sleep(0.12)
        m.handle_event("PreToolUse", "Bash")  # renews the count
        time.sleep(0.12)
        self.assertEqual(m.tick(), st.WORKING_BASH)


class TestConcurrency(unittest.TestCase):
    """The HTTP server writes from its thread and Qt reads from its own.

    Note what each test here is worth. The first one only proves that hammering
    `set_state` raises nothing and leaves a valid state — which is true with no
    lock at all, because assigning an attribute is atomic in CPython. The
    second is the one that actually exercises the lock: the read-modify-write
    inside `_alive()`, where the registry is pruned and *then* a decision is
    made from what is left.
    """

    def test_writes_from_several_threads(self):
        m = StateManager()
        states = [st.THINKING, st.WORKING, st.WAITING, st.IDLE]
        errors = []

        def hammer():
            try:
                for _ in range(200):
                    for s in states:
                        m.set_state(s)
                        self.assertIn(m.state, st.STATES)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=hammer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertIn(m.state, st.STATES)


class TestTheRegistryUnderConcurrency(unittest.TestCase):
    """The half of the lock that had no test at all.

    `_alive()` walks `_sessions`, deletes the stale ones and then decides
    whether the widget was left alone. If the server thread registers a session
    while the Qt thread is midway through that, the walk collapses. This is the
    sequence the lock exists for.
    """

    def setUp(self):
        self._alive = sm.SESSION_ALIVE
        # A race whose window is a handful of bytecodes practically never shows
        # up at the default switch interval: the suite passed with the lock
        # removed. Shortening it turns "eventually, on someone's machine" into
        # "reliably, here".
        self._interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)

    def tearDown(self):
        sm.SESSION_ALIVE = self._alive
        sys.setswitchinterval(self._interval)

    def test_the_session_registry_survives_concurrent_use(self):
        # Every session is stale on arrival: maximum churn, so the pruning and
        # the registering collide as often as possible.
        sm.SESSION_ALIVE = 0.0
        m = StateManager()
        errors: list = []
        stop = threading.Event()

        def register(n: int) -> None:
            try:
                for i in range(600):
                    m.handle_event("UserPromptSubmit", ts=time.time(),
                                   session=f"s{n}-{i}")
            except Exception as exc:  # noqa: BLE001 — recording is the point
                errors.append(exc)

        def ask() -> None:
            try:
                while not stop.is_set():
                    m.abandoned()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        readers = [threading.Thread(target=ask) for _ in range(4)]
        writers = [threading.Thread(target=register, args=(n,))
                   for n in range(4)]
        for t in readers + writers:
            t.start()
        for t in writers:
            t.join()
        stop.set()
        for t in readers:
            t.join()

        self.assertEqual(errors, [], f"the registry broke: {errors[:3]}")


class TestABrokenClock(unittest.TestCase):
    """Regression: one event from the future froze the widget for good.

    `_last_ts` had no ceiling, so an absurd timestamp became the ordering
    reference and every later event was discarded as old. The watchdog still
    ran, so the avatar dropped to `idle` and stayed there while Claude worked.

    The realistic trigger is not an attacker but a clock that moved: NTP
    stepping backwards, a VM resuming from suspend, or a dual-boot machine
    keeping the clock in local time.
    """

    def test_a_timestamp_from_the_future_does_not_freeze_it(self):
        m = StateManager()
        m.handle_event("Stop", ts=time.time() + 10 * 365 * 24 * 3600,
                       session="s1")

        # A brand new turn, which is the moment everything should come back to
        # life. With the bad timestamp adopted this was discarded as old, and
        # so was every event after it for the rest of the session.
        started = m.handle_event("UserPromptSubmit", ts=time.time(),
                                 session="s1")
        self.assertNotEqual(started, st.DONE,
                            "the widget was left frozen by one bad clock")
        self.assertEqual(
            m.handle_event("PreToolUse", "Bash", ts=time.time(), session="s1"),
            st.WORKING_BASH,
        )

    def test_the_event_still_counts_even_with_a_bad_clock(self):
        # Only the ordering claim is dropped. Something *is* happening, and
        # ignoring the event outright would be its own kind of lying.
        m = StateManager()
        self.assertEqual(m.handle_event("Stop", ts=time.time() + 1e6), st.DONE)

    def test_a_plausible_clock_is_still_trusted(self):
        # The margin must not be so tight that ordering stops working: an event
        # a moment ahead is normal and still has to win over an older one.
        m = StateManager()
        now = time.time()
        m.handle_event("Stop", ts=now + 1.0, session="s1")
        self.assertEqual(
            m.handle_event("PostToolUse", ts=now - 5.0, session="s1"),
            st.DONE,
            "an out-of-order straggler was allowed through",
        )


class TestLeavingWithTheSessions(unittest.TestCase):
    """The widget arrives with the work session and leaves with it.

    The clock starts when the last session goes, never at startup: the
    `SessionStart` that opens the widget is the one event that gets lost,
    because the hook sends it before the port is bound.
    """

    def setUp(self):
        self._close, self._alive = sm.CLOSE_AFTER, sm.SESSION_ALIVE

    def tearDown(self):
        sm.CLOSE_AFTER, sm.SESSION_ALIVE = self._close, self._alive

    def test_ghost_sessions_do_not_start_the_clock(self):
        # Four of these fire on every app start. If they counted, opening
        # Claude Code and then reading for five minutes took the dragon away.
        sm.CLOSE_AFTER = 0.0
        m = StateManager()
        for i in range(4):
            m.handle_event("SessionStart", ts=i, session=f"ghost{i}")
            m.handle_event("SessionEnd", ts=i, session=f"ghost{i}")
        self.assertFalse(m.abandoned(), "the ghosts of the app start counted")

    def test_a_widget_no_session_ever_touched_stays(self):
        # Opened by hand to draw sprites: no session opened it, so no session
        # gets to close it. This is why the clock is not started at startup.
        sm.CLOSE_AFTER = 0.0
        m = StateManager()
        self.assertFalse(m.abandoned())

    def test_a_live_session_keeps_it_open(self):
        sm.CLOSE_AFTER = 0.0
        m = StateManager()
        m.handle_event("SessionStart", ts=1, session="A")
        self.assertFalse(m.abandoned())

    def test_the_last_one_leaving_starts_the_clock(self):
        sm.CLOSE_AFTER = 0.0
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1, session="A")
        m.handle_event("SessionEnd", ts=2, session="A")
        self.assertTrue(m.abandoned())

    def test_the_grace_is_respected(self):
        # `SessionEnd`/`SessionStart` pairs seconds apart are common: with no
        # grace the avatar would close and reopen all day long.
        m = StateManager()  # the real five minutes
        m.handle_event("SessionStart", ts=1, session="A")
        m.handle_event("SessionEnd", ts=2, session="A")
        self.assertFalse(m.abandoned())

    def test_a_session_coming_back_calls_it_off(self):
        sm.CLOSE_AFTER = 0.0
        m = StateManager()
        m.handle_event("SessionStart", ts=1, session="A")
        m.handle_event("SessionEnd", ts=2, session="A")
        m.handle_event("SessionStart", ts=3, session="B")
        self.assertFalse(m.abandoned())

    def test_one_window_closing_is_not_everyone_leaving(self):
        sm.CLOSE_AFTER = 0.0
        m = StateManager()
        m.handle_event("SessionStart", ts=1, session="A")
        m.handle_event("SessionStart", ts=2, session="B")
        m.handle_event("SessionEnd", ts=3, session="A")
        self.assertFalse(m.abandoned())

    def test_silence_also_starts_the_clock(self):
        # The safety net for when the `SessionEnd` never arrives: Claude Code
        # killed outright, the POST lost, the plugin uninstalled with the
        # widget open.
        sm.CLOSE_AFTER, sm.SESSION_ALIVE = 0.0, 0.0
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1, session="A")
        self.assertTrue(m.abandoned())

    def test_a_pending_notice_holds_it_open(self):
        # Half an hour of silence while the dragon is asking the user
        # something is not an abandoned widget: it is what `waiting` is for.
        sm.CLOSE_AFTER, sm.SESSION_ALIVE = 0.0, 0.0
        m = StateManager()
        m.handle_event("UserPromptSubmit", ts=1, session="A")
        m.handle_event("Notification", ts=2, session="A")
        self.assertEqual(m.state, st.WAITING)
        self.assertFalse(m.abandoned())

    def test_the_notice_running_out_lets_it_go(self):
        """The two safety nets meeting: `waiting` lasts eight hours, a silent
        session dies at half an hour.

        While the notice stands the widget stays, however long the silence.
        Once the watchdog takes the notice away the session is just silent,
        the silence net lets it go, the dragon falls asleep and the widget
        leaves. Nobody is coming back after eight hours away.
        """
        sm.CLOSE_AFTER, sm.SESSION_ALIVE = 0.0, 0.0
        after, default = dict(st.STALL_AFTER), st.STALL_DEFAULT
        st.STALL_AFTER = {st.WAITING: 0.05}
        try:
            m = StateManager()
            m.handle_event("UserPromptSubmit", ts=1, session="A")
            m.handle_event("Notification", ts=2, session="A")
            self.assertFalse(m.abandoned(), "it left with a question open")
            time.sleep(0.06)
            self.assertEqual(m.tick(), st.SLEEP)
            self.assertTrue(m.abandoned())
        finally:
            st.STALL_AFTER, st.STALL_DEFAULT = after, default


if __name__ == "__main__":
    unittest.main(verbosity=2)
