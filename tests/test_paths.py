"""Where the program looks for its own files."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

QApplication.instance() or QApplication([])

import main  # noqa: E402


class TestBaseDir(unittest.TestCase):
    def test_it_is_the_project_folder(self):
        self.assertEqual(main.ROOT, ROOT)

    def test_the_sprites_and_the_preferences_follow_it(self):
        # Both hang off the same folder, so a packaged build cannot end up
        # reading sprites from one place and preferences from another.
        self.assertEqual(main.ASSETS.parent, main.ROOT)


class TestWhoStartedIt(unittest.TestCase):
    """Whether there is a person watching this launch.

    The desktop app opens four sessions at once and each tries to start the
    widget; only one wins the port. Telling a person "it is already running"
    helps when they double-clicked the launcher twice — the losers of that
    race have nothing to say to anybody.
    """

    def argv(self, *args: str):
        original = sys.argv
        sys.argv = ["main.py", *args]
        self.addCleanup(lambda: setattr(sys, "argv", original))

    def test_a_hook_launch_is_quiet(self):
        self.argv("--quiet")
        self.assertTrue(main.started_by_a_hook())

    def test_a_person_gets_the_dialog(self):
        self.argv()
        self.assertFalse(main.started_by_a_hook())


if __name__ == "__main__":
    unittest.main(verbosity=2)
