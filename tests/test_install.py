"""The manual hook registration, for the desktop app.

Everything here is about one promise: whatever else the user keeps in
`~/.claude/settings.json` survives untouched.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import install  # noqa: E402
import uninstall  # noqa: E402


class BaseSettings(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "settings.json"
        original = install.SETTINGS
        install.SETTINGS = self.path
        uninstall.SETTINGS = self.path
        self.addCleanup(lambda: setattr(install, "SETTINGS", original))
        self.addCleanup(lambda: setattr(uninstall, "SETTINGS", original))
        # The scripts report what they did; the suite does not need to hear it.
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def write(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def read(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def a_foreign_hook(self) -> dict:
        """Somebody else's hook, which must survive everything we do."""
        return {
            "matcher": "Write",
            "hooks": [{"type": "command", "command": "prettier --write"}],
        }


class TestInstalling(BaseSettings):
    def test_it_works_with_no_settings_file_at_all(self):
        install.main()
        self.assertTrue(self.path.is_file())
        self.assertEqual(
            set(self.read()["hooks"]),
            set(install.EVENTS) | set(install.LAUNCH_EVENTS),
        )

    def test_the_launcher_is_registered_too(self):
        """Without this the dragon never appears in the desktop app."""
        install.main()
        hooks = self.read()["hooks"]
        for event in install.LAUNCH_EVENTS:
            args = hooks[event][0]["hooks"][0]["args"]
            self.assertTrue(args[0].endswith("launch.py"), args)

    def test_events_report_through_notify(self):
        install.main()
        hooks = self.read()["hooks"]
        for event in install.EVENTS:
            args = hooks[event][0]["hooks"][0]["args"]
            self.assertTrue(args[0].endswith("notify.py"), args)

    def test_every_other_setting_is_left_alone(self):
        self.write({
            "model": "opus",
            "theme": "dark-ansi",
            "enabledPlugins": {"claude-cute@claude-cute": True},
            "permissions": {"allow": ["Bash(git *)"]},
        })
        install.main()
        after = self.read()
        self.assertEqual(after["model"], "opus")
        self.assertEqual(after["theme"], "dark-ansi")
        self.assertEqual(after["enabledPlugins"], {"claude-cute@claude-cute": True})
        self.assertEqual(after["permissions"], {"allow": ["Bash(git *)"]})

    def test_hooks_from_other_tools_survive(self):
        self.write({"hooks": {"PreToolUse": [self.a_foreign_hook()]}})
        install.main()
        groups = self.read()["hooks"]["PreToolUse"]
        commands = [
            e["command"] for g in groups for e in g["hooks"]
        ]
        self.assertIn("prettier --write", commands)
        self.assertEqual(len(groups), 2)

    def test_hooks_on_events_we_do_not_touch_survive(self):
        self.write({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "say done"}
        ]}]}})
        install.main()
        after = self.read()["hooks"]
        self.assertEqual(after["Stop"][0]["hooks"][0]["command"], "say done")

    def test_installing_twice_does_not_pile_up(self):
        install.main()
        install.main()
        install.main()
        groups = self.read()["hooks"]["PreToolUse"]
        self.assertEqual(len(groups), 1)

    def test_a_broken_settings_file_is_never_overwritten(self):
        self.path.write_text("{ not json at all", encoding="utf-8")
        with self.assertRaises(SystemExit):
            install.main()
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{ not json at all")

    def test_it_leaves_a_backup(self):
        self.write({"model": "opus"})
        install.main()
        spare = self.path.with_suffix(".json.claude-cute-backup")
        self.assertTrue(spare.is_file())
        self.assertEqual(json.loads(spare.read_text(encoding="utf-8")),
                         {"model": "opus"})

    def test_it_does_not_duplicate_the_reporting_events(self):
        """The plugin already delivers these, so only the launcher goes here."""
        install.main()
        registered = set(self.read()["hooks"])
        self.assertNotIn("Stop", registered)
        self.assertNotIn("SessionEnd", registered)
        self.assertNotIn("Notification", registered)

    def test_matchers_only_where_they_are_accepted(self):
        install.main()
        hooks = self.read()["hooks"]
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "*")
        self.assertNotIn("matcher", hooks["PostToolBatch"][0])


class TestUninstalling(BaseSettings):
    def test_it_removes_what_we_added(self):
        install.main()
        uninstall.main()
        self.assertNotIn("hooks", self.read())

    def test_other_settings_survive(self):
        self.write({"model": "opus", "theme": "dark-ansi"})
        install.main()
        uninstall.main()
        after = self.read()
        self.assertEqual(after["model"], "opus")
        self.assertEqual(after["theme"], "dark-ansi")

    def test_hooks_from_other_tools_survive(self):
        self.write({"hooks": {"PreToolUse": [self.a_foreign_hook()]}})
        install.main()
        uninstall.main()
        groups = self.read()["hooks"]["PreToolUse"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["hooks"][0]["command"], "prettier --write")

    def test_uninstalling_without_installing_changes_nothing(self):
        self.write({"model": "opus"})
        uninstall.main()
        self.assertEqual(self.read(), {"model": "opus"})

    def test_it_survives_having_no_settings_file(self):
        self.assertEqual(uninstall.main(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
