"""Tests for the hook.

`hooks/notify.py` is the file that **must never fail**: it runs on every Claude
Code tool call and its contract is to exit 0 no matter what. Ever since it
started reading the port from `config.json` it has logic of its own, and that
logic needs a net.

The sending is tested against real servers on free ports, because the promise
that matters most — *with the widget closed, nothing happens* — lives in the
code that talks to the network.
"""

from __future__ import annotations

import importlib
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "hooks"))

import notify  # noqa: E402


class BaseNotify(unittest.TestCase):
    """Builds a fake project with whatever `config.json` each test asks for."""

    def with_config(self, contents: str | None) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "hooks").mkdir()
        fake = root / "hooks" / "notify.py"
        fake.write_text("", encoding="utf-8")
        if contents is not None:
            (root / "config.json").write_text(contents, encoding="utf-8")

        # `_url` works out the root from its own `__file__`, so we point that
        # at the fake file instead of touching the real project.
        original = notify.__file__
        notify.__file__ = str(fake)
        self.addCleanup(lambda: setattr(notify, "__file__", original))
        return notify._url()


class TestHookPort(BaseNotify):
    def test_no_config_uses_the_usual_port(self):
        self.assertIn(f":{notify.DEFAULT_PORT}/", self.with_config(None))

    def test_config_without_the_key(self):
        self.assertIn(f":{notify.DEFAULT_PORT}/",
                      self.with_config('{"character": "dragoncita"}'))

    def test_it_honours_the_configured_port(self):
        # The whole point of the fix: the widget and the hook read the same
        # file, so they cannot end up pointing at different ports.
        self.assertIn(":8771/", self.with_config(json.dumps({"port": 8771})))

    def test_a_broken_config_does_not_blow_up(self):
        self.assertIn(f":{notify.DEFAULT_PORT}/",
                      self.with_config("{ this is not json"))

    def test_a_config_with_a_bom(self):
        # Notepad saves with a BOM and it already wiped the preferences once.
        raw = "﻿" + json.dumps({"port": 8771})
        self.assertIn(":8771/", self.with_config(raw))

    def test_an_out_of_range_port_is_ignored(self):
        for bad in (99999, 80, -1, 0):
            with self.subTest(port=bad):
                self.assertIn(f":{notify.DEFAULT_PORT}/",
                              self.with_config(json.dumps({"port": bad})))

    def test_a_junk_port_is_ignored(self):
        self.assertIn(f":{notify.DEFAULT_PORT}/",
                      self.with_config(json.dumps({"port": "eight thousand"})))

    def test_it_always_returns_a_usable_url(self):
        for contents in (None, "", "{ broken", "[]", "null",
                         json.dumps({"port": None})):
            with self.subTest(config=contents):
                url = self.with_config(contents)
                self.assertTrue(url.startswith("http://127.0.0.1:"))
                self.assertTrue(url.endswith("/event"))


class BaseSending(unittest.TestCase):
    """Exercises the actual send, against real sockets on free ports.

    Testing only the path that returns before touching the network left the
    hook's whole reason for existing — two attempts, the `except`, the final
    `return 0` — with no net at all.
    """

    def point_at(self, port: int) -> None:
        original = notify.URL
        notify.URL = f"http://127.0.0.1:{port}/event"
        self.addCleanup(lambda: setattr(notify, "URL", original))

    def widget(self) -> list:
        """A real server that records what arrives. Returns that list."""
        received: list = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 (http.server API)
                length = int(self.headers.get("Content-Length", 0))
                received.append(json.loads(self.rfile.read(length)))
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):  # keeps the test output clean
                pass

        httpd = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(
            target=httpd.serve_forever, args=(0.05,), daemon=True
        ).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.point_at(httpd.server_address[1])
        return received

    def dead_port(self) -> None:
        """Points the hook at a port nobody is listening on."""
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        self.point_at(port)

    def mute_port(self) -> None:
        """Points it at a socket that accepts and then says nothing."""
        mute = socket.socket()
        mute.bind(("127.0.0.1", 0))
        mute.listen(1)
        self.addCleanup(mute.close)
        self.point_at(mute.getsockname()[1])

    def with_proxy(self, value: str) -> None:
        original = os.environ.get("HTTP_PROXY")
        os.environ["HTTP_PROXY"] = value

        def restore():
            if original is None:
                os.environ.pop("HTTP_PROXY", None)
            else:
                os.environ["HTTP_PROXY"] = original

        self.addCleanup(restore)

    def run_hook(self, event: str = "PreToolUse", tool: str = "Bash") -> int:
        payload = {"hook_event_name": event, "tool_name": tool,
                   "session_id": "s1"}
        argv, stdin = sys.argv, sys.stdin
        sys.argv = ["notify.py"]
        sys.stdin = io.StringIO(json.dumps(payload))
        try:
            return notify.main()
        finally:
            sys.argv, sys.stdin = argv, stdin


class TestSending(BaseSending):
    def test_the_event_reaches_the_widget(self):
        received = self.widget()
        self.assertEqual(self.run_hook(), 0)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["event"], "PreToolUse")
        self.assertEqual(received[0]["tool"], "Bash")
        self.assertEqual(received[0]["session"], "s1")

    def test_a_configured_proxy_never_sees_the_events(self):
        """Regression: loopback is not in the default proxy bypass list.

        With a proxy configured, `urlopen` would POST every event —session id
        included— to that proxy instead of to the widget, and the dragon would
        sit inert with no way to find out why.
        """
        received = self.widget()
        self.with_proxy("http://proxy.invalid:3128")
        self.assertEqual(self.run_hook(), 0)
        self.assertEqual(len(received), 1,
                         "the event went to the proxy instead of the widget")

    def test_with_the_widget_closed_it_still_exits_zero(self):
        # The golden rule: a closed widget has to be indistinguishable from a
        # running one, or Claude Code shows an error on every tool call.
        self.dead_port()
        self.assertEqual(self.run_hook(), 0)

    def test_a_mute_widget_does_not_blow_the_time_budget(self):
        # A socket that accepts and never answers is the worst case: both
        # attempts run to their timeout. This sits on Claude Code's critical
        # path, so the budget is the point.
        self.mute_port()
        started = time.monotonic()
        self.assertEqual(self.run_hook(), 0)
        spent = time.monotonic() - started
        budget = sum(notify.ATTEMPTS)
        self.assertLess(spent, budget + 1.0,
                        f"spent {spent:.2f}s against a budget of {budget:.2f}s")


class TestContract(unittest.TestCase):
    def test_with_no_event_it_exits_zero(self):
        # A hook that cannot do anything useful still has to exit cleanly.
        original = sys.argv
        sys.argv = ["notify.py"]
        try:
            stream = importlib.import_module("io").StringIO("")
            real, sys.stdin = sys.stdin, stream
            try:
                self.assertEqual(notify.main(), 0)
            finally:
                sys.stdin = real
        finally:
            sys.argv = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
