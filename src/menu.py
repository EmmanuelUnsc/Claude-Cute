"""The avatar's action menu, reached by right-clicking the avatar."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QWidget

from .states import SESSION_STATES

if TYPE_CHECKING:  # type hints only; never imported at runtime
    from .avatar_window import AvatarWindow

# How long "Hide for" can hide the avatar. Always a deadline, never a switch.
HIDE_OPTIONS: tuple[tuple[str, int], ...] = (
    ("15 minutes", 15),
    ("1 hour", 60),
    ("4 hours", 240),
)


def _submenu(menu: QMenu, title: str) -> QMenu:
    """A submenu that Qt owns, not Python.

    Use this instead of `menu.addMenu(title)`, which hands ownership to Python
    and leaves the entry pointing at nothing once the wrapper is collected.
    """
    sub = QMenu(title, menu)
    menu.addMenu(sub)
    return sub


def build_menu(window: AvatarWindow, parent: QWidget | None = None) -> QMenu:
    """A fresh menu, already populated."""
    return populate_menu(QMenu(parent), window)


def populate_menu(menu: QMenu, window: AvatarWindow) -> QMenu:
    """Fills (or refills) the action menu.

    Three blocks: who the avatar is, where it sits and when it shows, and
    leaving. Repopulated on every opening, since its contents depend on which
    character is active and which states already have sprites.
    """
    menu.clear()

    # --- who the avatar is ---
    characters = window.engine.characters()
    if len(characters) > 1:
        choose = _submenu(menu, "Character")
        for name in characters:
            action = QAction(name, choose)
            action.setCheckable(True)
            action.setChecked(name == window.engine.character)
            action.triggered.connect(
                lambda _checked=False, n=name: window.set_character(n)
            )
            choose.addAction(action)

    # Every state the session can produce; the ones without their own sprites
    # are marked, which doubles as a checklist while drawing. `dragged` is not
    # here: you preview it by dragging the avatar.
    own = set(window.engine.available_states())
    force = _submenu(menu, "Force state")
    for state in SESSION_STATES:
        label = state if state in own else f"{state}  · inherited"
        action = QAction(label, force)
        action.triggered.connect(
            lambda _checked=False, s=state: window.force_state(s)
        )
        force.addAction(action)

    # --- where it sits and when it shows ---
    menu.addSeparator()

    hide = _submenu(menu, "Hide for")
    for label, minutes in HIDE_OPTIONS:
        action = QAction(label, hide)
        action.triggered.connect(
            lambda _checked=False, m=minutes: window.hide_for(m)
        )
        hide.addAction(action)

    corner = QAction("Move to corner", menu)
    corner.triggered.connect(window.move_to_corner)
    menu.addAction(corner)

    reload_action = QAction("Reload assets", menu)
    reload_action.triggered.connect(window.reload_assets)
    menu.addAction(reload_action)

    # --- leaving ---
    menu.addSeparator()

    quit_action = QAction("Quit", menu)
    quit_action.triggered.connect(window.quit)
    menu.addAction(quit_action)

    return menu
