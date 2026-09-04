"""Local HTTP server that receives the events from Claude Code's hooks.

It uses the stdlib's `http.server` to keep dependencies at zero and the
footprint low. It runs on a daemon thread so it never blocks the UI.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .state_manager import StateManager

HOST = "127.0.0.1"
PORT = 8770

# How many ports to try if the preferred one is held by an unrelated program.
PORTS_TO_TRY = 6

# Cap on the request body. Legitimate ones are a few dozen bytes.
MAX_BODY = 8192


class _Handler(BaseHTTPRequestHandler):
    manager: StateManager  # injected when the class is created

    # Bounds a client that announces more bytes than it sends.
    timeout = 2

    def handle_error(self, request, client_address) -> None:
        """Swallows the noise of a client that hung up, and nothing else."""
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)

    def _host_is_ours(self) -> bool:
        """Whether the request addressed this widget and not a hostile name.

        Guards against DNS rebinding, which a content-type check alone does not
        stop.
        """
        host = (self.headers.get("Host") or "").strip()
        name = host.rsplit(":", 1)[0] if ":" in host else host
        return name in ("127.0.0.1", "localhost", "[::1]", "::1")

    def do_POST(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        if not self._host_is_ours():
            self._json(403, {"error": "unexpected Host"})
            return

        if self.path.rstrip("/") != "/event":
            self._json(404, {"error": "not found"})
            return

        # Forces a browser into a preflight this server does not answer, so an
        # ordinary web page cannot POST here.
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if content_type != "application/json":
            self._json(415, {"error": "Content-Type: application/json required"})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._json(400, {"error": "invalid Content-Length"})
            return

        if length > MAX_BODY:
            self._json(413, {"error": f"body too large (max {MAX_BODY})"})
            return

        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "invalid json"})
            return

        if not isinstance(payload, dict):
            self._json(400, {"error": "expected a json object"})
            return

        try:
            if "state" in payload:
                state = self.manager.set_state(str(payload["state"]))
            else:
                # `tool` picks the animation family; without it, generic work.
                tool = payload.get("tool")
                try:
                    ts = float(payload["ts"]) if "ts" in payload else None
                except (TypeError, ValueError):
                    ts = None
                session = payload.get("session")
                state = self.manager.handle_event(
                    str(payload.get("event", "")),
                    str(tool) if tool else None,
                    ts,
                    str(session) if session else None,
                )
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return

        self._json(200, {"state": state})

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_is_ours():
            self._json(403, {"error": "unexpected Host"})
            return
        if self.path.rstrip("/") in ("/state", ""):
            self._json(200, {"state": self.manager.state})
        else:
            self._json(404, {"error": "not found"})

    def _json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:
        """Silences the per-request log to stderr."""


class _Server(ThreadingHTTPServer):
    # False on purpose: failing to bind the port *is* the single-instance
    # control. True would let duplicate widgets pile up silently on Windows.
    allow_reuse_address = False


class AlreadyRunning(OSError):
    """The port is held by another Claude Cute, not by some other program."""


def is_widget(host: str = HOST, port: int = PORT) -> bool:
    """Whether a Claude Cute answers on that port, and not some other program.

    Called at startup only, with proxies disabled since the widget is always on
    loopback.
    """
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(
            f"http://{host}:{port}/state", timeout=0.5
        ) as response:
            data = json.loads(response.read(MAX_BODY))
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return isinstance(data, dict) and "state" in data


def serve_on_free_port(
    manager: StateManager,
    host: str = HOST,
    preferred: int = PORT,
    attempts: int = PORTS_TO_TRY,
    poll_interval: float = 0.5,
) -> tuple[_Server, int]:
    """Starts on the first free port from `preferred`. Returns which one it used.

    Another Claude Cute on the port raises `AlreadyRunning`; an unrelated
    program just means trying the next one. The caller must record the chosen
    port in `config.json`, which is where `hooks/notify.py` reads it.
    """
    last: OSError | None = None
    for port in range(preferred, preferred + attempts):
        try:
            return start_server(manager, host, port, poll_interval), port
        except OSError as exc:
            if is_widget(host, port):
                raise AlreadyRunning(
                    f"a Claude Cute is already on {host}:{port}"
                ) from exc
            last = exc
    raise OSError(
        f"no free port found between {preferred} and {preferred + attempts - 1}"
    ) from last


def start_server(
    manager: StateManager,
    host: str = HOST,
    port: int = PORT,
    poll_interval: float = 0.5,
) -> _Server:
    """Starts the server on a daemon thread and returns the instance.

    Raises `OSError` if the port is taken. `poll_interval` only affects how
    long `shutdown()` takes to return; it exists to keep the tests fast.
    """
    handler = type("BoundHandler", (_Handler,), {"manager": manager})
    httpd = _Server((host, port), handler)
    threading.Thread(
        target=httpd.serve_forever, args=(poll_interval,), daemon=True
    ).start()
    return httpd
