"""Tests for finding the Claude Code process above a hook.

The walk is tested on made-up process trees, so it does not depend on what
happens to be running. The trees are the ones that matter: the one measured
from the desktop app, a terminal, an npm install, and a hook run by hand.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import claude_process as cp  # noqa: E402


def tree(*chain: tuple[int, str]):
    """A lookup for a straight line of processes, child first."""
    table = {}
    for (pid, name), parent in zip(chain, chain[1:] + ((0, ""),)):
        table[pid] = (parent[0], name)
    return table.get


class TestFind(unittest.TestCase):
    def test_the_desktop_app(self):
        # Measured: each desktop session is its own claude.exe, under the app's.
        lookup = tree(
            (10, "python.exe"), (11, "py.exe"), (12, "bash.exe"),
            (13, "bash.exe"), (14, "bash.exe"),
            (20, "claude.exe"),  # the session
            (30, "claude.exe"),  # the desktop app
            (40, "sihost.exe"),
        )
        self.assertEqual(cp.find(10, lookup), 20)

    def test_a_terminal(self):
        lookup = tree(
            (10, "python3"), (11, "bash"), (20, "claude"),
            (30, "zsh"), (40, "Terminal"),
        )
        self.assertEqual(cp.find(10, lookup), 20)

    def test_an_npm_install_runs_on_node(self):
        lookup = tree(
            (10, "python.exe"), (11, "bash.exe"), (20, "node.exe"),
            (30, "pwsh.exe"), (40, "WindowsTerminal.exe"),
        )
        self.assertEqual(cp.find(10, lookup), 20)

    def test_python_by_any_of_its_names(self):
        for name in ("python3.13", "pythonw.exe", "Python313.EXE"):
            lookup = tree((10, name), (11, name), (20, "claude"))
            self.assertEqual(cp.find(10, lookup), 20, name)

    def test_a_hook_run_by_hand_finds_nothing(self):
        # `python notify.py PreToolUse Bash` from a terminal: the first thing
        # above the shell is the terminal itself. No pid beats a wrong one.
        lookup = tree(
            (10, "python.exe"), (11, "pwsh.exe"), (12, "WindowsTerminal.exe"),
            (13, "explorer.exe"),
        )
        self.assertIsNone(cp.find(10, lookup))

    def test_it_does_not_return_itself(self):
        # A Claude Code that ran this module directly is not "above" it.
        lookup = tree((10, "claude.exe"), (11, "explorer.exe"))
        self.assertIsNone(cp.find(10, lookup))

    def test_a_parent_that_is_gone(self):
        lookup = {10: (11, "python.exe")}.get
        self.assertIsNone(cp.find(10, lookup))

    def test_a_cycle_does_not_hang(self):
        lookup = {10: (11, "bash"), 11: (10, "bash")}.get
        self.assertIsNone(cp.find(10, lookup))


class TestNeverRaises(unittest.TestCase):
    def test_a_broken_system_gives_none(self):
        def boom():
            raise OSError("no snapshot for you")

        original = cp._windows_table, cp._proc, cp._ps
        cp._windows_table = boom
        cp._proc = cp._ps = lambda pid: boom()
        try:
            self.assertIsNone(cp.claude_pid())
        finally:
            cp._windows_table, cp._proc, cp._ps = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
