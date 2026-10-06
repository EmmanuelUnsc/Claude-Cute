"""Tests for the process watcher, against real processes.

A child Python is started and killed, which is the same thing that happens to
Claude Code when its terminal closes.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.processes import ProcessWatch  # noqa: E402


def _child() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


class TestProcessWatch(unittest.TestCase):
    def setUp(self):
        self.watch = ProcessWatch()
        self.addCleanup(self.watch.forget_all)

    def test_a_running_process_is_alive(self):
        child = _child()
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        self.assertIs(self.watch.alive(child.pid), True)

    def test_a_killed_process_is_gone(self):
        child = _child()
        self.assertIs(self.watch.alive(child.pid), True)
        child.kill()
        child.wait()
        self.assertIs(self.watch.alive(child.pid), False)

    def test_a_pid_that_does_not_exist_is_gone(self):
        # Spawned and reaped before the watch ever looks: the closest a test
        # gets to a session whose process died before its first event landed.
        child = _child()
        child.kill()
        child.wait()
        self.assertIs(self.watch.alive(child.pid), False)

    def test_forgetting_lets_go_of_the_pid(self):
        child = _child()
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        self.watch.alive(child.pid)
        self.watch.forget(child.pid)
        self.assertNotIn(child.pid, self.watch._handles)

    def test_forgetting_an_unknown_pid_is_harmless(self):
        self.watch.forget(123456789)

    @unittest.skipUnless(sys.platform == "win32", "Windows access rules")
    def test_a_process_it_may_not_open_is_unknown(self):
        # The System process (pid 4) refuses even the narrowest rights. That
        # must read as "cannot say", never as "gone".
        self.assertIsNone(self.watch.alive(4))


if __name__ == "__main__":
    unittest.main(verbosity=2)
