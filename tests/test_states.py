"""Tests for the state table.

`states.py` is pure data and pure functions: nothing to build, no threads and
no clocks. If a test in here needs to wait, it is in the wrong file.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import states as st
from src.states import ancestors, state_for, stall_limit


class TestAncestors(unittest.TestCase):
    def test_a_child_walks_up_to_the_root(self):
        self.assertEqual(
            ancestors("working-bash"), ["working-bash", "working", "idle"]
        )

    def test_a_flat_state_falls_back_to_idle(self):
        self.assertEqual(ancestors("thinking"), ["thinking", "idle"])

    def test_idle_is_not_duplicated(self):
        self.assertEqual(ancestors("idle"), ["idle"])

    def test_a_child_of_idle(self):
        self.assertEqual(ancestors("idle-sleep"), ["idle-sleep", "idle"])

    def test_every_state_ends_in_idle(self):
        for state in st.STATES:
            self.assertEqual(
                ancestors(state)[-1], st.IDLE, f"{state} does not end in idle"
            )

    def test_explicit_parent(self):
        # waiting is nobody's child by name, but it inherits from thinking.
        self.assertEqual(ancestors("waiting"), ["waiting", "thinking", "idle"])
        self.assertEqual(
            ancestors("compacting"), ["compacting", "thinking", "idle"]
        )

    def test_explicit_parents_point_at_valid_states(self):
        for child, parent in st.PARENTS.items():
            self.assertIn(child, st.STATES)
            self.assertIn(parent, st.STATES)

    def test_no_infinite_cycles(self):
        # A badly declared parent must not hang the resolution.
        original = dict(st.PARENTS)
        try:
            st.PARENTS["waiting"] = "compacting"
            st.PARENTS["compacting"] = "waiting"
            chain = ancestors("waiting")
            self.assertEqual(chain[-1], st.IDLE)
            self.assertEqual(len(chain), len(set(chain)))
        finally:
            st.PARENTS.clear()
            st.PARENTS.update(original)

    def test_an_unknown_state_still_resolves(self):
        # A future Claude Code event must not break the resolution.
        self.assertEqual(
            ancestors("future-odd"), ["future-odd", "future", "idle"]
        )


class TestEventMapping(unittest.TestCase):
    def test_the_main_events(self):
        cases = {
            "SessionStart": st.WAKE,
            "UserPromptSubmit": st.THINKING,
            "PostToolUse": st.THINKING,
            "PostToolUseFailure": st.ERROR,
            "PermissionRequest": st.WAITING,
            "PreCompact": st.COMPACTING,
            "Stop": st.DONE,
            "StopFailure": st.ERROR_API,
            "SessionEnd": st.SLEEP,
        }
        for event, expected in cases.items():
            self.assertEqual(state_for(event), expected, event)

    def test_an_unknown_event_falls_back_to_idle(self):
        self.assertEqual(state_for("EventThatDoesNotExist"), st.IDLE)

    def test_pretooluse_without_a_tool_is_generic(self):
        self.assertEqual(state_for("PreToolUse"), st.WORKING)

    def test_the_tool_families(self):
        cases = {
            "Bash": st.WORKING_BASH,
            "Edit": st.WORKING_EDIT,
            "Write": st.WORKING_EDIT,
            "Read": st.WORKING_READ,
            "Grep": st.WORKING_READ,
            "WebSearch": st.WORKING_WEB,
            "Task": st.WORKING_AGENT,
        }
        for tool, expected in cases.items():
            self.assertEqual(state_for("PreToolUse", tool), expected, tool)

    def test_an_unknown_tool_falls_back_to_generic(self):
        self.assertEqual(state_for("PreToolUse", "BrandNewTool"), st.WORKING)

    def test_the_tool_does_not_affect_other_events(self):
        # Only PreToolUse is refined; Stop is still Stop.
        self.assertEqual(state_for("Stop", "Bash"), st.DONE)


class TestStallLimit(unittest.TestCase):
    """`stall_limit` is a table lookup, with nothing live behind it."""

    def setUp(self):
        self._stall = dict(st.STALL_AFTER)

    def tearDown(self):
        st.STALL_AFTER = self._stall

    def test_tools_get_more_slack_than_the_rest(self):
        # A build can take minutes without producing a single event.
        self.assertGreater(stall_limit(st.WORKING), stall_limit(st.THINKING))
        self.assertEqual(stall_limit(st.WORKING_BASH), stall_limit(st.WORKING))

    def test_waiting_lasts_a_working_day(self):
        # `waiting` waits for a person. If it gave up like the rest, the notice
        # would vanish exactly when the user is not looking, which is exactly
        # when it is useful. It has to cover a meeting, a lunch, or leaving and
        # coming back the next day.
        self.assertGreaterEqual(stall_limit(st.WAITING), 8 * 3600)

    def test_waiting_still_expires_eventually(self):
        # Not infinite, on purpose: if the event that resolves it were lost,
        # the avatar would show something false forever.
        self.assertLess(stall_limit(st.WAITING), float("inf"))

    def test_the_limits_are_short(self):
        # Showing something that is no longer true is noticeable; the send
        # already retries, so getting stuck is rare and there is no need to be
        # this forgiving.
        self.assertLessEqual(stall_limit(st.WORKING), 120.0)
        self.assertLessEqual(stall_limit(st.THINKING), 45.0)

    def test_the_limit_is_inherited_from_the_ancestor(self):
        st.STALL_AFTER = {st.WORKING: 42.0}
        self.assertEqual(stall_limit(st.WORKING_EDIT), 42.0)


class TestCoherence(unittest.TestCase):
    def test_compacting_by_hand_does_not_leave_the_avatar_thinking(self):
        # `PostCompact` only says the compaction finished. Assuming Claude was
        # still working left the avatar thinking for 45 seconds while the user
        # was already back at the prompt.
        self.assertEqual(state_for("PostCompact"), st.IDLE)

    def test_every_event_maps_to_a_declared_state(self):
        for event, state in st.EVENTS.items():
            self.assertIn(state, st.STATES, f"{event} -> {state}")

    def test_every_family_maps_to_a_declared_state(self):
        for tool, state in st.FAMILIES.items():
            self.assertIn(state, st.STATES, f"{tool} -> {state}")

    def test_every_declared_state_has_a_description(self):
        # Without this, adding a state and forgetting to describe it leaves
        # whoever explains the dragon out loud reading the raw id, and nobody
        # finds out until it is on screen.
        missing = [s for s in st.STATES if s not in st.DESCRIPTIONS]
        self.assertEqual(missing, [], "states with no description")

    def test_there_are_no_leftover_descriptions(self):
        # The other way round: a description for a state that no longer exists
        # is junk that survived a deletion.
        extra = [s for s in st.DESCRIPTIONS if s not in st.STATES]
        self.assertEqual(extra, [], "descriptions of non-existent states")

    def test_the_work_families_are_children_of_working(self):
        # Nearly every tool is some form of working, which is why its family
        # hangs off `working`. The exception is in the test below.
        for tool, state in st.FAMILIES.items():
            if state == st.WAITING:
                continue
            self.assertIn(st.WORKING, ancestors(state), f"{tool} -> {state}")

    def test_asking_the_user_is_not_working(self):
        # There used to be a rule requiring every family to be a child of
        # `working`. It was relaxed on purpose: `AskUserQuestion` is Claude
        # waiting for an answer, not Claude working.
        self.assertEqual(st.FAMILIES["AskUserQuestion"], st.WAITING)

    def test_every_terminal_tool_does_the_same_thing(self):
        # `PowerShell` was missing and fell into generic `working` 73 times in
        # the measurements: a terminal that was not breathing fire.
        for tool in ("Bash", "PowerShell"):
            self.assertEqual(st.FAMILIES[tool], st.WORKING_BASH)

    def test_every_transient_points_at_valid_states(self):
        for source, (duration, target) in st.TRANSIENTS.items():
            self.assertIn(source, st.STATES)
            self.assertIn(target, st.STATES)
            self.assertGreater(duration, 0)


class TestTheTwoInheritances(unittest.TestCase):
    """`PARENTS` answers a question about pixels; `kinds()` one about meaning.

    They used to be the same chain, so a placeholder chosen for how a state
    *looks* handed down a timeout nobody had thought about.
    """

    def test_a_visual_parent_does_not_lend_its_timeout(self):
        # `dragged` borrows `waiting`'s drawings while it has none of its own...
        self.assertIn(st.WAITING, st.ancestors(st.DRAGGED))
        # ...but not its eight hours, which exist because a person is answering.
        self.assertEqual(st.stall_limit(st.DRAGGED), st.STALL_DEFAULT)

    def test_the_name_hierarchy_does_lend_it(self):
        # `working-bash` really is a kind of `working`: what holds for the
        # parent holds for the child, so the 120 s are inherited on purpose.
        self.assertEqual(st.stall_limit(st.WORKING_BASH),
                         st.STALL_AFTER[st.WORKING])

    def test_changing_the_drawing_table_cannot_change_a_timeout(self):
        # The guard for the whole class of problem: whoever picks a visual
        # placeholder in the future must not be able to alter expiry by doing
        # it. `waiting` is the dangerous one, with its eight hours.
        original = dict(st.PARENTS)
        st.PARENTS[st.THINKING] = st.WAITING  # absurd, and that is the point
        try:
            self.assertNotIn(st.WAITING, st.kinds(st.THINKING))
            self.assertEqual(st.stall_limit(st.THINKING), st.STALL_DEFAULT)
        finally:
            st.PARENTS.clear()
            st.PARENTS.update(original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
