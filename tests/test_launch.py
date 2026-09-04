"""Tests for the launcher hook.

`hooks/launch.py` runs when a session opens and when you write a prompt. Its
whole job is to notice the dragon is gone and bring it back, and its contract
is the same as the notifier's: **never fail**, whatever happens.
"""

from __future__ import annotations

import os
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "hooks"))

import launch  # noqa: E402


class TestTheStartingMark(unittest.TestCase):
    """Four sessions open at once when the desktop app starts.

    Each runs this hook, and the widget takes ~1.6 s to bind its port — so
    without a mark they all look, see nothing, and start four widgets. Three
    lose the race and die. The port keeps that correct either way; the mark is
    what keeps it quiet.
    """

    def folder(self) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return tmp.name

    def test_the_first_one_through_gets_to_launch(self):
        self.assertFalse(launch.someone_else_is_starting_it(self.folder()))

    def test_the_ones_right_behind_it_stand_down(self):
        root = self.folder()
        launch.someone_else_is_starting_it(root)
        for _ in range(3):  # the other three sessions of the app start
            self.assertTrue(launch.someone_else_is_starting_it(root))

    def test_the_mark_goes_stale(self):
        # Otherwise a widget that died would stay unrevivable for as long as
        # the mark said someone was starting it.
        root = self.folder()
        launch.someone_else_is_starting_it(root)
        original, launch.STARTING_UP = launch.STARTING_UP, 0.0
        try:
            self.assertFalse(launch.someone_else_is_starting_it(root))
        finally:
            launch.STARTING_UP = original

    def test_a_folder_it_cannot_write_to_does_not_stop_it(self):
        # Better one extra widget that dies on the port than no dragon at all.
        self.assertFalse(
            launch.someone_else_is_starting_it(os.path.join(self.folder(), "nope")))


class TestTheCheck(unittest.TestCase):
    def test_a_dead_port_means_it_is_not_running(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        original = launch.notify.URL
        launch.notify.URL = f"http://127.0.0.1:{port}/event"
        self.addCleanup(lambda: setattr(launch.notify, "URL", original))
        self.assertFalse(launch.already_running())

    def test_it_exits_zero_even_with_everything_broken(self):
        # The golden rule it shares with the notifier: a hook that fails is
        # worse than a hook that does nothing.
        original = launch.notify.URL
        launch.notify.URL = "http://127.0.0.1:1/event"  # nothing there, ever
        self.addCleanup(lambda: setattr(launch.notify, "URL", original))
        broken, launch.launch = launch.launch, lambda: 1 / 0
        try:
            self.assertEqual(launch.main(), 0)
        finally:
            launch.launch = broken


if __name__ == "__main__":
    unittest.main(verbosity=2)
