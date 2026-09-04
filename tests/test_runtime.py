"""Tests for fetching the graphics library.

The plugin carries the program but not PySide6 — a hundred megabytes of
platform binaries. `hooks/runtime.py` gets it once, into a folder of its own,
and everything here is about the two ways that can go wrong at scale: several
sessions starting the same download at once, and a machine that simply cannot
do it retrying forever.
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "hooks"))

import runtime  # noqa: E402


class BaseRuntime(unittest.TestCase):
    """Points the module at a throwaway folder: no test touches the real one."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self._original = (runtime.HOME, runtime.LIB,
                          runtime.SENTINEL, runtime.COOLDOWN)
        runtime.HOME = self.home
        runtime.LIB = self.home / "lib"
        runtime.SENTINEL = self.home / ".installing"
        runtime.COOLDOWN = self.home / ".install-failed"

    def tearDown(self):
        (runtime.HOME, runtime.LIB,
         runtime.SENTINEL, runtime.COOLDOWN) = self._original

    def never_runs_anything(self):
        """Fails the test if pip is actually invoked."""
        def boom(*a, **k):
            self.fail("it started a real download")
        original, runtime._quiet_run = runtime._quiet_run, boom
        self.addCleanup(lambda: setattr(runtime, "_quiet_run", original))


class TestWhenItInstalls(BaseRuntime):
    def test_a_machine_that_already_has_it_downloads_nothing(self):
        original, runtime.can_draw = runtime.can_draw, lambda p: True
        self.addCleanup(lambda: setattr(runtime, "can_draw", original))
        self.never_runs_anything()
        self.assertTrue(runtime.ready("python"))

    def test_a_second_session_does_not_start_a_second_download(self):
        # Four sessions open at once when the desktop app starts, and each one
        # runs the launcher. Without the sentinel they would all pull the same
        # hundred megabytes at the same time.
        self.home.mkdir(parents=True, exist_ok=True)
        runtime.SENTINEL.write_text(str(time.time()), encoding="utf-8")
        self.never_runs_anything()
        self.assertFalse(runtime.install("python"))

    def test_a_stuck_sentinel_does_not_block_it_forever(self):
        # If a session died mid-install, the mark it left behind must not make
        # the dragon unrecoverable from then on.
        self.home.mkdir(parents=True, exist_ok=True)
        runtime.SENTINEL.write_text("x", encoding="utf-8")

        attempts = []

        class Done:
            returncode = 0
            stdout = b""

        original_run, original_draw = runtime._quiet_run, runtime.can_draw
        original_window = runtime.INSTALL_WINDOW
        runtime._quiet_run = lambda *a, **k: (attempts.append(a) or Done())
        runtime.can_draw = lambda p: True
        runtime.INSTALL_WINDOW = 0.0   # the mark has already expired
        try:
            self.assertTrue(runtime.install("python"))
            self.assertTrue(attempts, "a stale mark blocked the install")
        finally:
            runtime._quiet_run, runtime.can_draw = original_run, original_draw
            runtime.INSTALL_WINDOW = original_window


class TestWhenItFails(BaseRuntime):
    def fails_with(self, code: int):
        class Done:
            returncode = code
            stdout = b"pip said no"
        runtime._quiet_run = lambda *a, **k: Done()
        runtime.can_draw = lambda p: False

    def setUp(self):
        super().setUp()
        self._run, self._draw = runtime._quiet_run, runtime.can_draw
        self.addCleanup(lambda: setattr(runtime, "_quiet_run", self._run))
        self.addCleanup(lambda: setattr(runtime, "can_draw", self._draw))

    def test_a_failure_is_recorded(self):
        self.fails_with(1)
        self.assertFalse(runtime.install("python"))
        self.assertTrue(runtime.COOLDOWN.is_file())
        self.assertIn("pip said no", runtime.COOLDOWN.read_text(encoding="utf-8"))

    def test_it_does_not_retry_on_every_session(self):
        # Someone with no network would otherwise start a hundred-megabyte
        # download every time they open Claude Code, for ever.
        self.fails_with(1)
        runtime.install("python")
        self.never_runs_anything()
        self.assertFalse(runtime.install("python"))

    def test_the_sentinel_is_released_even_when_it_fails(self):
        self.fails_with(1)
        runtime.install("python")
        self.assertFalse(runtime.SENTINEL.exists())

    def test_an_interpreter_that_does_not_exist_says_no_instead_of_raising(self):
        runtime._quiet_run, runtime.can_draw = self._run, self._draw
        self.assertFalse(runtime.can_draw(str(self.home / "no-such-python")))


class TestTheLibraryFolder(BaseRuntime):
    def test_it_goes_on_the_path_once_it_exists(self):
        self.assertNotIn(str(runtime.LIB),
                         runtime.environment().get("PYTHONPATH", ""))
        runtime.LIB.mkdir(parents=True)
        self.assertIn(str(runtime.LIB), runtime.environment()["PYTHONPATH"])

    def test_it_does_not_trample_an_existing_path(self):
        import os
        runtime.LIB.mkdir(parents=True)
        original = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = "/somewhere/of/the/user"
        try:
            self.assertIn("/somewhere/of/the/user", runtime.environment()["PYTHONPATH"])
        finally:
            if original is None:
                os.environ.pop("PYTHONPATH", None)
            else:
                os.environ["PYTHONPATH"] = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
