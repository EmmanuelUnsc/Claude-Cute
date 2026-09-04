"""Makes sure the interpreter that runs the widget can import PySide6.

The plugin carries the program but not the graphics library, so the first time
the dragon is asked for on a machine without it, this fetches it once into
`~/.claude/claude-cute/`. That directory is the only thing the project puts
outside its own folder; uninstalling means deleting it.

It never fails and never blocks: a machine with no network simply gets no
dragon.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

# Everything this puts on the user's machine lives here, and nowhere else.
HOME = Path.home() / ".claude" / "claude-cute"
LIB = HOME / "lib"

# Marks an install in flight, so concurrent sessions do not all download.
SENTINEL = HOME / ".installing"
INSTALL_WINDOW = 20 * 60.0

# After a failed install, wait this long before trying again.
COOLDOWN = HOME / ".install-failed"
COOLDOWN_WINDOW = 6 * 3600.0

INSTALL_TIMEOUT = 15 * 60.0
IMPORT_TIMEOUT = 30.0

# Kept in step with `requirements.txt`.
PACKAGE = "PySide6>=6.7,<7"


def _quiet_run(args: list[str], timeout: float, env: dict | None = None):
    """Runs a command with no console window and no output of its own."""
    options: dict = {
        "timeout": timeout,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "env": env,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(args, **options)


def environment() -> dict:
    """The environment the widget has to run under to see the library."""
    env = dict(os.environ)
    if LIB.is_dir():
        previous = env.get("PYTHONPATH")
        env["PYTHONPATH"] = f"{LIB}{os.pathsep}{previous}" if previous else str(LIB)
    return env


def can_draw(python: str) -> bool:
    """Whether that interpreter can import PySide6, ours or the system's."""
    try:
        done = _quiet_run([python, "-c", "import PySide6"], IMPORT_TIMEOUT,
                          env=environment())
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def _fresh(mark: Path, window: float) -> bool:
    try:
        return time.time() - mark.stat().st_mtime < window
    except OSError:
        return False


def _note(mark: Path, text: str = "") -> None:
    try:
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.write_text(text or str(time.time()), encoding="utf-8")
    except OSError:
        pass


def install(python: str) -> bool:
    """Fetches PySide6 into our own folder. Returns whether it worked."""
    if _fresh(SENTINEL, INSTALL_WINDOW) or _fresh(COOLDOWN, COOLDOWN_WINDOW):
        return False

    _note(SENTINEL)
    try:
        done = _quiet_run(
            [python, "-m", "pip", "install", "--target", str(LIB),
             "--upgrade", PACKAGE],
            INSTALL_TIMEOUT,
        )
        if done.returncode == 0 and can_draw(python):
            return True
        output = (done.stdout or b"")[-2000:].decode("utf-8", "replace")
        _note(COOLDOWN, f"{time.ctime()}\nexit {done.returncode}\n\n{output}")
        return False
    except (OSError, subprocess.SubprocessError) as exc:
        _note(COOLDOWN, f"{time.ctime()}\n{exc!r}")
        return False
    finally:
        try:
            SENTINEL.unlink()
        except OSError:
            pass


def ready(python: str) -> bool:
    """Whether the widget can be started with that interpreter, installing if
    it has to."""
    return can_draw(python) or install(python)
