"""Entry point: starts the event server and the avatar window."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from src.animation_engine import AnimationEngine
from src.avatar_window import AvatarWindow
from src.config import FILENAME as CONFIG_FILENAME, Config
from src.server import HOST, PORT, AlreadyRunning, serve_on_free_port
from src.state_manager import StateManager


# The folder everything else hangs off: sprites and preferences.
ROOT = Path(__file__).parent
ASSETS = ROOT / "assets"


def started_by_a_hook() -> bool:
    """Whether nobody is watching this launch, so errors stay silent."""
    return "--quiet" in sys.argv


def _warn(title: str, text: str) -> None:
    """Shows the error on the console and in a dialog box."""
    print(f"[claude-cute] {title}: {text}")
    if not started_by_a_hook():
        QMessageBox.warning(None, title, text)


def _report(engine: AnimationEngine) -> None:
    """Console summary for whoever draws sprites: what is drawn, what is not."""
    own = engine.available_states()
    inherited = engine.missing_states()
    print(f"[claude-cute] character: {engine.character_name} "
          f"({engine.frame_px}px x{engine.scale})")
    print(f"[claude-cute] own sprites ({len(own)}): {', '.join(own)}")
    if inherited:
        print(f"[claude-cute] inheriting from an ancestor: {', '.join(inherited)}")

    for state, dur_ms, limit_s in engine.truncated_states():
        print(
            f"[claude-cute] heads up: '{state}' lasts {dur_ms} ms but expires "
            f"at {int(limit_s * 1000)} ms; it will be cut short. Adjust "
            f"TRANSIENTS in src/states.py or drop frames."
        )

    for state, spare_ms, limit_s in engine.frozen_states():
        print(
            f"[claude-cute] heads up: '{state}' finishes its animation and "
            f"then sits {spare_ms} ms frozen on the last frame (it expires at "
            f"{int(limit_s * 1000)} ms). Lower TRANSIENTS or add frames."
        )


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    config = Config(ROOT / CONFIG_FILENAME).load()
    manager = StateManager()
    engine = AnimationEngine(ASSETS, config.character)

    _report(engine)

    preferred = config.port or PORT
    try:
        _server, port = serve_on_free_port(manager, preferred=preferred)
    except AlreadyRunning:
        _warn(
            "Claude Cute is already running",
            f"There is already a widget listening on {HOST}:{preferred}.\n\n"
            "Check your screen, or close it with a right click and try again.",
        )
        return 1
    except OSError as exc:
        _warn(
            "No free port found",
            f"Tried from {preferred} up and they are all taken by other "
            "programs.\n\n"
            f"Detail: {exc}",
        )
        return 1

    # The hooks read the port from this same file, so a move has to be recorded.
    if port != preferred:
        print(f"[claude-cute] port {preferred} was taken by another program; "
              f"moved to {port}")
        config.port = port
        if not config.save():
            print("[claude-cute] heads up: could not record the port in "
                  "config.json, so the hooks will keep looking for the old one")

    print(f"[claude-cute] listening for events on http://{HOST}:{port}/event")

    window = AvatarWindow(manager, engine, config)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
