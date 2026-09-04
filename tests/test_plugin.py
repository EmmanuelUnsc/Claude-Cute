"""Tests for the plugin manifests.

They are data files nobody executes while the widget runs, so nothing else
would notice if they drifted: a typo in an event name, a hook pointing at a
path that moved, or the plugin listening for something the widget throws away.
The cost of that drift is a dragon that stops reacting, silently.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import states as st  # noqa: E402


def _load(*parts: str) -> dict:
    return json.loads((ROOT.joinpath(*parts)).read_text(encoding="utf-8"))


class TestHooksManifest(unittest.TestCase):
    def setUp(self):
        self.hooks = _load("hooks", "hooks.json")["hooks"]

    def entries(self):
        for event, groups in self.hooks.items():
            for group in groups:
                for hook in group["hooks"]:
                    yield event, hook

    def test_it_listens_for_exactly_what_the_widget_understands(self):
        # Both directions matter. An event the widget ignores is a hook process
        # spawned for nothing on Claude Code's critical path; an event the
        # widget knows and the plugin never sends is an animation that can
        # never happen.
        self.assertEqual(set(self.hooks), set(st.EVENTS))

    def test_every_hook_runs_a_script_from_the_plugin_folder(self):
        # The absolute path in the old instructions broke silently whenever the
        # folder moved. This is what replaces it.
        for event, hook in self.entries():
            with self.subTest(event=event):
                target = hook["args"][0]
                self.assertTrue(
                    target.startswith("${CLAUDE_PLUGIN_ROOT}/hooks/"), target)
                name = target.rsplit("/", 1)[-1]
                self.assertTrue((ROOT / "hooks" / name).is_file(), name)

    def test_every_event_tells_the_widget_what_happened(self):
        # Whatever else an event does, the notifier has to run for it: that is
        # the only thing that moves the dragon.
        for event, groups in self.hooks.items():
            with self.subTest(event=event):
                scripts = [h["args"][0].rsplit("/", 1)[-1]
                           for g in groups for h in g["hooks"]]
                self.assertIn("notify.py", scripts)

    def test_the_launcher_runs_when_a_session_opens_and_when_you_write(self):
        """Two moments, and neither is on the path of every tool call.

        `SessionStart` is the obvious one. `UserPromptSubmit` is the safety
        net: whatever takes the dragon away — a bug of ours, a manual quit, a
        crash — **the next thing you type brings it back**. Prompts are far
        rarer than tool calls, so the extra process barely registers.

        The rest of the eighteen events are deliberately left out: checking
        whether the dragon is up costs a request, and spending it on every
        single thing Claude does would buy nothing.
        """
        launching = sorted(event for event, hook in self.entries()
                           if hook["args"][0].endswith("launch.py"))
        self.assertEqual(launching, ["SessionStart", "UserPromptSubmit"])

    def test_every_hook_uses_the_exec_form(self):
        """No shell, on any platform.

        The shell form runs under `sh` on Linux and macOS but under Git Bash on
        Windows — or PowerShell when Git Bash is not installed, which cannot
        parse the same commands. The exec form has no shell at all.
        """
        for event, hook in self.entries():
            with self.subTest(event=event):
                self.assertIn("args", hook)
                self.assertNotIn(" ", hook["command"])

    def test_every_hook_is_asynchronous(self):
        # The one thing that must never happen is holding up a turn.
        for event, hook in self.entries():
            with self.subTest(event=event):
                self.assertTrue(hook.get("async"))

    def test_the_scripts_it_points_at_exist(self):
        for name in ("notify.py", "launch.py"):
            self.assertTrue((ROOT / "hooks" / name).is_file(), name)


class TestPluginManifest(unittest.TestCase):
    def test_the_hooks_sit_where_they_are_picked_up_by_convention(self):
        """Regression: declaring them as well loads the file twice.

        `hooks/hooks.json` at the plugin root is loaded automatically. Adding
        `"hooks": "./hooks/hooks.json"` to the manifest made Claude Code refuse
        the whole plugin with *duplicate hooks file detected* — and validation
        did not catch it, because the shape was perfectly correct. That field
        is only for **additional** hook files somewhere else.
        """
        self.assertTrue((ROOT / "hooks" / "hooks.json").is_file())
        self.assertNotIn("hooks", _load(".claude-plugin", "plugin.json"))

    def test_the_interpreter_is_asked_for_once_and_has_a_default(self):
        # One question at install, with an answer already filled in, is the
        # closest this can get to no question at all while still working on a
        # machine where Python is called something else.
        option = _load(".claude-plugin", "plugin.json")["userConfig"]["python"]
        self.assertEqual(option["type"], "string")
        self.assertTrue(option["default"])

    def test_the_hooks_use_the_interpreter_that_was_asked_for(self):
        plugin = _load(".claude-plugin", "plugin.json")
        declared = set(plugin["userConfig"])
        hooks = _load("hooks", "hooks.json")["hooks"]
        for groups in hooks.values():
            for group in groups:
                for hook in group["hooks"]:
                    key = hook["command"].removeprefix(
                        "${user_config.").removesuffix("}")
                    self.assertIn(key, declared)

    def test_the_marketplace_points_at_this_repository(self):
        market = _load(".claude-plugin", "marketplace.json")
        self.assertTrue(market["owner"]["name"])
        names = [p["name"] for p in market["plugins"]]
        self.assertIn(_load(".claude-plugin", "plugin.json")["name"], names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
