"""Claude Code hook: tells the widget what is happening in the session.

It receives the hook payload on stdin and POSTs it to the local server. It never
blocks and never fails: if the widget is not running, the hook does nothing.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_PORT = 8770


def _url() -> str:
    """The widget's URL, with whatever port `config.json` says."""
    port = DEFAULT_PORT
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "config.json"), encoding="utf-8-sig") as f:
            value = int(json.load(f)["port"])
        if 1024 <= value <= 65535:
            port = value
    except Exception:  # noqa: BLE001 — swallowing everything *is* the policy
        pass
    return f"http://127.0.0.1:{port}/event"


URL = _url()

# The widget is always on loopback, so requests go out with proxies turned off.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# Time budget in seconds, one entry per delivery attempt.
ATTEMPTS = (0.25, 0.15)


def main() -> int:
    # The widget orders events by this timestamp.
    started_at = time.time()

    event = ""
    tool = None
    session = None

    try:
        raw = sys.stdin.read()
        if raw.strip():
            payload = json.loads(raw)
            event = str(payload.get("hook_event_name", ""))
            tool = payload.get("tool_name") or None
            session = payload.get("session_id") or None
    except (ValueError, json.JSONDecodeError, OSError):
        event = ""

    # Lets you force an event by hand:  python notify.py PreToolUse Bash
    if len(sys.argv) > 1:
        event = sys.argv[1]
    if len(sys.argv) > 2:
        tool = sys.argv[2]

    if not event:
        return 0

    body: dict[str, object] = {"event": event, "ts": started_at}
    if tool:
        body["tool"] = str(tool)
    if session:
        body["session"] = str(session)

    request = urllib.request.Request(
        URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for timeout in ATTEMPTS:
        try:
            OPENER.open(request, timeout=timeout).close()
            return 0
        except (urllib.error.URLError, OSError, TimeoutError):
            continue
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
