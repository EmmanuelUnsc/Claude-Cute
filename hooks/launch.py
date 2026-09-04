"""Claude Code hook: makes sure the widget is running.

Runs on `SessionStart` and `UserPromptSubmit`, alongside `notify.py`. If the
dragon is already up this does nothing; if it is not, it starts it and returns.
It never blocks and never fails: a machine without PySide6 simply gets no
dragon.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

# The hook's own folder is on `sys.path`, so the port logic comes from notify.
import notify
import runtime

# Seconds to wait for the widget to answer on the port.
CHECK_TIMEOUT = 0.4

# Seconds after a launch during which other launchers assume one is on its way.
STARTING_UP = 10.0
MARK = ".launching"


def already_running() -> bool:
    """Whether a Claude Cute answers on the port, and not some other program."""
    url = notify.URL.replace("/event", "/state")
    try:
        with notify.OPENER.open(url, timeout=CHECK_TIMEOUT) as answer:
            data = json.loads(answer.read(4096))
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return isinstance(data, dict) and "state" in data


def someone_else_is_starting_it(root: str) -> bool:
    """Whether another launcher already fired, moments ago."""
    mark = os.path.join(root, MARK)
    try:
        if time.time() - os.path.getmtime(mark) < STARTING_UP:
            return True
    except OSError:
        pass
    try:
        with open(mark, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except OSError:
        pass  # read-only folder: fall through and just launch
    return False


def launch() -> None:
    """Starts the widget detached, so it outlives this hook."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    entry = os.path.join(root, "main.py")
    if not os.path.isfile(entry):
        return

    if someone_else_is_starting_it(root):
        return

    # Fetches the graphics library once if this machine does not have it.
    if not runtime.ready(sys.executable):
        return

    options: dict = {
        "cwd": root,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        # So the widget sees the library wherever it ended up.
        "env": runtime.environment(),
    }
    if os.name == "nt":
        options["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        options["start_new_session"] = True

    # `--quiet` so a launcher that loses the race for the port dies silently.
    subprocess.Popen([sys.executable, entry, "--quiet"], **options)


def main() -> int:
    try:
        if not already_running():
            launch()
    except Exception:  # noqa: BLE001 — swallowing everything *is* the policy
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
