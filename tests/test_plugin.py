"""Tests for the plugin manifests.

They are data files nobody executes while the widget runs, so nothing else
would notice if they drifted: a typo in an event name, a hook pointing at a
path that moved, or the plugin listening for something the widget throws away.
The cost of that drift is a dragon that stops reacting, silently.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import states as st  # noqa: E402

# What every hook command has to look like. Anything else is a mistake we want
# to hear about at test time rather than from a user whose dragon sits still.
COMMAND = re.compile(
    r'^bash "\$\{CLAUDE_PLUGIN_ROOT\}/hooks/cute-python\.sh" '
    r'"\$\{CLAUDE_PLUGIN_ROOT\}/hooks/(\w+\.py)"$'
)


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

    def script(self, hook: dict) -> str:
        """The Python file a hook ends up running."""
        found = COMMAND.match(hook["command"])
        self.assertIsNotNone(found, hook["command"])
        return found.group(1)

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
                name = self.script(hook)
                self.assertTrue((ROOT / "hooks" / name).is_file(), name)

    def test_every_event_tells_the_widget_what_happened(self):
        # Whatever else an event does, the notifier has to run for it: that is
        # the only thing that moves the dragon.
        for event, groups in self.hooks.items():
            with self.subTest(event=event):
                scripts = [self.script(h) for g in groups for h in g["hooks"]]
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
                           if self.script(hook) == "launch.py")
        self.assertEqual(launching, ["SessionStart", "UserPromptSubmit"])

    def test_every_hook_goes_through_the_interpreter_shim(self):
        """Nothing names a Python directly, and nothing asks the user for one.

        Naming one is what broke this before. `python3` is the Microsoft Store
        stub on Windows — on the PATH, exits 49, runs nothing — and asking the
        user instead let them press Esc and install a plugin whose eighteen
        hooks Claude Code then refuses to run, two error lines per tool call.
        `cute-python.sh` is the single place allowed to decide, and it probes
        every candidate before trusting it.
        """
        for event, hook in self.entries():
            with self.subTest(event=event):
                self.assertRegex(hook["command"], COMMAND)

    def test_the_shim_is_shipped_and_starts_with_a_shebang(self):
        shim = ROOT / "hooks" / "cute-python.sh"
        self.assertTrue(shim.is_file())
        first = shim.read_text(encoding="utf-8").splitlines()[0]
        self.assertTrue(first.startswith("#!"), first)

    def test_the_shim_keeps_its_windows_defences(self):
        """Three bugs that cost somebody else a debugging session each.

        They are invisible in the happy path and each one produces a dragon
        that never appears, so a well-meaning cleanup would take them out
        without noticing. `PYTHONUTF8` stops cp1252 from breaking any path with
        a non-Latin byte; `cygpath` stops Git Bash's `/c/Users/...` from
        reaching a native `python.exe`, which reads it as the root of the
        current drive; and probing the version is what unmasks the Store stub.
        """
        text = (ROOT / "hooks" / "cute-python.sh").read_text(encoding="utf-8")
        self.assertIn("PYTHONUTF8=1", text)
        self.assertIn("cygpath", text)
        self.assertIn("sys.version_info", text)

    def test_the_shim_never_writes_to_the_console(self):
        """Silence is the feature.

        Eighteen hooks fire on every tool call, so one line on stderr is two
        lines of noise per call, forever. Every failure path exits 0 and leaves
        its reasons in a file the doctor reads on request.
        """
        text = (ROOT / "hooks" / "cute-python.sh").read_text(encoding="utf-8")
        body = [line for line in text.splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
        for line in body:
            self.assertNotIn("echo ", line)
            self.assertNotIn(">&2", line)
        self.assertNotIn("exit 1", text)

    def test_every_hook_is_asynchronous(self):
        # The one thing that must never happen is holding up a turn.
        for event, hook in self.entries():
            with self.subTest(event=event):
                self.assertTrue(hook.get("async"))

    def test_the_scripts_it_points_at_exist(self):
        for name in ("notify.py", "launch.py", "cute-python.sh"):
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

    def test_installing_asks_the_user_nothing(self):
        """Regression, and the reason this release exists.

        1.0.0 declared a `userConfig` option for the Python command. Pressing
        Esc on that question installed the plugin anyway, left `pluginConfigs`
        empty in `settings.json`, and Claude Code then refused to run all
        eighteen hooks — printing an error per hook per event in the terminal,
        and nothing at all in the desktop app, which does not surface hook
        errors. Answering it was no better: the offered default, `python3`, is
        the Microsoft Store stub on Windows.

        No official Anthropic plugin declares `userConfig`. Neither does this
        one any more; `cute-python.sh` works it out instead.
        """
        self.assertNotIn("userConfig", _load(".claude-plugin", "plugin.json"))

    def test_the_marketplace_points_at_this_repository(self):
        market = _load(".claude-plugin", "marketplace.json")
        self.assertTrue(market["owner"]["name"])
        names = [p["name"] for p in market["plugins"]]
        self.assertIn(_load(".claude-plugin", "plugin.json")["name"], names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
