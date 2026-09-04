"""Tests for the event server.

`server.py` is plain Python, no Qt: it is started and stopped in every test. It
uses high ports so it does not clash with the real widget, which may be running
while the suite does.
"""

from __future__ import annotations

import http.client
import json
import socket
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.server import (  # noqa: E402
    AlreadyRunning,
    is_widget,
    serve_on_free_port,
    start_server,
)
from src.state_manager import StateManager  # noqa: E402

BASE = 8930  # the tests' own range

# Every `shutdown()` waits out one poll cycle. With the default half second,
# shutting down the servers in these tests took ten seconds and the suite
# stopped being something you run all the time.
POLL = 0.01


class BaseServer(unittest.TestCase):
    def start(self, port: int) -> None:
        """A real Claude Cute on that port."""
        httpd = start_server(StateManager(), port=port, poll_interval=POLL)
        # addCleanup runs in reverse: the socket close has to be registered
        # first so it executes *after* the server is shut down.
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)

    def occupy(self, port: int) -> None:
        """Some unrelated program, answering something else."""

        class Stranger(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = b"i am not claude cute"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        httpd = HTTPServer(("127.0.0.1", port), Stranger)
        threading.Thread(
            target=httpd.serve_forever, args=(POLL,), daemon=True
        ).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)

    def block(self, port: int) -> None:
        """A mute socket: it holds the port and answers nothing."""
        s = socket.socket()
        s.bind(("127.0.0.1", port))
        s.listen(1)
        self.addCleanup(s.close)

    def serve(self, preferred: int, attempts: int = 6) -> int:
        httpd, port = serve_on_free_port(
            StateManager(),
            preferred=preferred,
            attempts=attempts,
            poll_interval=POLL,
        )
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return port


class TestIsWidget(BaseServer):
    def test_it_recognises_its_own(self):
        self.start(BASE)
        self.assertTrue(is_widget(port=BASE))

    def test_a_stranger_is_not_a_widget(self):
        # The whole point of the fix: a taken port does not prove the widget is
        # already running.
        self.occupy(BASE + 1)
        self.assertFalse(is_widget(port=BASE + 1))

    def test_an_empty_port_is_not_a_widget(self):
        self.assertFalse(is_widget(port=BASE + 2))

    def test_a_mute_socket_does_not_hang(self):
        # It accepts the connection and never answers: without the timeout the
        # startup would wait forever and the widget would never open.
        self.block(BASE + 3)
        self.assertFalse(is_widget(port=BASE + 3))


class TestFreePort(BaseServer):
    def test_it_uses_the_preferred_one_if_free(self):
        self.assertEqual(self.serve(BASE + 10), BASE + 10)

    def test_it_moves_if_a_stranger_holds_it(self):
        self.occupy(BASE + 20)
        self.assertEqual(self.serve(BASE + 20), BASE + 21)

    def test_it_skips_as_many_strangers_as_needed(self):
        for i in range(3):
            self.occupy(BASE + 30 + i)
        self.assertEqual(self.serve(BASE + 30), BASE + 33)

    def test_another_claude_cute_stops_the_search(self):
        # Single-instance control: moving here would start a duplicate.
        self.start(BASE + 40)
        with self.assertRaises(AlreadyRunning):
            self.serve(BASE + 40)

    def test_a_widget_further_along_stops_it_too(self):
        # Even if a stranger holds the preferred port, running into another
        # widget on the way has to stop us all the same.
        self.occupy(BASE + 50)
        self.start(BASE + 51)
        with self.assertRaises(AlreadyRunning):
            self.serve(BASE + 50)

    def test_with_no_free_ports_it_gives_up(self):
        for i in range(3):
            self.occupy(BASE + 60 + i)
        with self.assertRaises(OSError) as box:
            self.serve(BASE + 60, attempts=3)
        self.assertNotIsInstance(box.exception, AlreadyRunning)


class TestProtocol(BaseServer):
    def request(self, port: int, body: bytes, kind: str = "application/json"):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/event",
            data=body,
            headers={"Content-Type": kind},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=2) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:  # unclosed, Python warns about a leaked resource
                return e.code, None

    def test_it_accepts_an_event(self):
        self.start(BASE + 70)
        code, body = self.request(
            BASE + 70, json.dumps({"event": "PreToolUse", "tool": "Bash"}).encode()
        )
        self.assertEqual(code, 200)
        self.assertEqual(body["state"], "working-bash")

    def test_it_rejects_anything_but_json(self):
        # Without this, any web page could POST to it from the browser.
        self.start(BASE + 71)
        code, _ = self.request(BASE + 71, b"{}", kind="text/plain")
        self.assertEqual(code, 415)

    def test_it_rejects_a_huge_body(self):
        self.start(BASE + 72)
        code, _ = self.request(BASE + 72, b"x" * 9000)
        self.assertEqual(code, 413)

    def test_it_rejects_invalid_json(self):
        self.start(BASE + 73)
        code, _ = self.request(BASE + 73, b"{ broken")
        self.assertEqual(code, 400)

    def test_an_unknown_state_gives_400(self):
        self.start(BASE + 74)
        code, _ = self.request(
            BASE + 74, json.dumps({"state": "does-not-exist"}).encode()
        )
        self.assertEqual(code, 400)


class TestHardening(BaseServer):
    """What keeps a browser, and a slow client, from getting anywhere."""

    def talk(self, port: int, host_header: str, length: str | None = None,
             body: bytes = b'{"state": "thinking"}', wait: float = 8.0):
        """One request with the `Host` and `Content-Length` we choose.

        `http.client` is used instead of raw bytes so the protocol is its
        problem, but with `skip_host` so the header under test is ours.
        """
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=wait)
        self.addCleanup(conn.close)
        conn.putrequest("POST", "/event", skip_host=True)
        conn.putheader("Host", host_header)
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", length or str(len(body)))
        conn.endheaders()
        conn.send(body)
        return conn

    def test_a_foreign_host_header_is_refused(self):
        """Regression: requiring `application/json` does not stop DNS rebinding.

        A hostile site can point its own domain at 127.0.0.1; from then on the
        browser treats the request as same-origin and sends no preflight. The
        one thing it cannot forge is the `Host` header.
        """
        port = BASE + 20
        self.start(port)
        self.assertEqual(self.talk(port, "evil.example.com").getresponse().status,
                         403)

    def test_localhost_is_still_welcome(self):
        # The README tells people to poke the widget with curl, and plenty of
        # them will type localhost. The server only binds loopback, so that
        # name is as much ours as the literal address.
        port = BASE + 21
        self.start(port)
        self.assertEqual(
            self.talk(port, f"localhost:{port}").getresponse().status, 200)

    def test_a_lying_content_length_does_not_park_a_thread(self):
        # A client announcing 500 bytes and sending two used to leave a thread
        # waiting for the rest for as long as the widget lived.
        port = BASE + 22
        self.start(port)
        conn = self.talk(port, f"127.0.0.1:{port}", length="500", body=b"{}")
        started = time.monotonic()
        try:
            conn.getresponse()
        except Exception:  # noqa: BLE001 — hanging up is a valid answer here
            pass
        spent = time.monotonic() - started
        self.assertLess(spent, 5.0, "the connection was left hanging")
        self.assertTrue(is_widget(port=port), "it stopped serving everyone else")


if __name__ == "__main__":
    unittest.main(verbosity=2)
