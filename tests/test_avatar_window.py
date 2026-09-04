"""Tests for the overlay window.

They run headless with Qt's `offscreen` platform.
"""

from __future__ import annotations

import gc
import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QCursor, QGuiApplication, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src import menu as menu_mod  # noqa: E402
from src import smoothing as smoothing_mod  # noqa: E402
from src.animation_engine import AnimationEngine  # noqa: E402
from src.avatar_window import AvatarWindow  # noqa: E402
from src.config import Config  # noqa: E402
from src import states as st  # noqa: E402
from src.state_manager import StateManager  # noqa: E402

_app = QApplication.instance() or QApplication([])
# The test windows carry WA_QuitOnClose, so destroying them would make Qt end
# the application... which here is the test runner itself.
_app.setQuitOnLastWindowClosed(False)


def _png(path: Path, side: int = 8, padding: int = 0) -> None:
    """A square sprite; `padding` leaves that many transparent pixels
    around it, the way a character sits on a roomier canvas."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    clear, solid = b"\x00\x00\x00\x00", b"\xff\x00\x00\xff"
    rows = []
    for y in range(side):
        if y < padding or y >= side - padding:
            rows.append(b"\x00" + clear * side)
        else:
            rows.append(b"\x00" + clear * padding
                        + solid * (side - 2 * padding) + clear * padding)
    raw = b"".join(rows)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class BaseWindow(unittest.TestCase):
    def make(
        self,
        side: int = 8,
        scale: int | None = None,
        config: Config | None = None,
        states: tuple[str, ...] = ("idle",),
        padding: int = 0,
    ) -> AvatarWindow:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "character"
        for state in states:
            (root / state).mkdir(parents=True)
            for i in range(2):
                _png(root / state / f"frame_{i + 1:02d}.png", side, padding)
        if scale is not None:
            import json

            (root / "character.json").write_text(
                json.dumps({"scale": scale}), encoding="utf-8"
            )
        engine = AnimationEngine(Path(tmp.name))
        window = AvatarWindow(StateManager(), engine, config)
        self.addCleanup(window.deleteLater)
        return window

    def temp_config(self) -> Config:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Config(Path(tmp.name) / "config.json").load()


class TestWindow(BaseWindow):
    def test_closing_ends_the_application(self):
        """Regression: `Qt.Tool` leaves `WA_QuitOnClose` at False.

        With the attribute off, closing the window hid the avatar but the
        process stayed alive holding port 8770, and the next launch said
        "already running" forever.
        """
        window = self.make()
        self.assertTrue(
            window.testAttribute(Qt.WA_QuitOnClose),
            "without WA_QuitOnClose the process goes zombie on close",
        )

    def test_it_stays_out_of_the_taskbar(self):
        flags = self.make().windowFlags()
        self.assertTrue(flags & Qt.Tool)
        self.assertTrue(flags & Qt.FramelessWindowHint)
        self.assertTrue(flags & Qt.WindowStaysOnTopHint)

    def test_transparent_background(self):
        self.assertTrue(self.make().testAttribute(Qt.WA_TranslucentBackground))

    def test_the_size_comes_from_the_character(self):
        window = self.make(side=8, scale=3)
        self.assertEqual(window.width(), 8 * 3)
        self.assertEqual(window.height(), 8 * 3)

    def test_moving_to_the_corner_leaves_it_visible(self):
        window = self.make()
        window.move(-5000, -5000)
        window.move_to_corner()
        screen = window.screen().availableGeometry()
        self.assertGreaterEqual(window.x(), screen.left())
        self.assertGreaterEqual(window.y(), screen.top())


class TestRememberedPosition(BaseWindow):
    def test_with_no_config_it_goes_to_the_corner(self):
        window = self.make()
        screen = window.screen().availableGeometry()
        self.assertLess(window.x(), screen.right())
        self.assertGreaterEqual(window.x(), screen.left())

    def test_it_saves_when_the_drag_is_released(self):
        config = self.temp_config()
        window = self.make(config=config)
        window.move(140, 160)
        window.remember_position()
        self.assertEqual(config.position, (140, 160))

    def test_it_restores_what_was_saved(self):
        config = self.temp_config()
        screen = QApplication.primaryScreen().availableGeometry()
        target = (screen.left() + 100, screen.top() + 120)
        config.position = target
        window = self.make(config=config)
        self.assertEqual((window.x(), window.y()), target)

    def test_an_off_screen_position_is_discarded(self):
        # A disconnected monitor leaves coordinates that no longer exist.
        # Restoring them would hide the avatar with no way to get it back.
        config = self.temp_config()
        config.position = (-9000, -9000)
        window = self.make(config=config)
        screen = window.screen().availableGeometry()
        self.assertGreaterEqual(window.x(), screen.left())
        self.assertGreaterEqual(window.y(), screen.top())

    def test_a_peeking_corner_is_not_enough(self):
        # If only a few pixels fit, it cannot be grabbed to drag it.
        config = self.temp_config()
        screen = QApplication.primaryScreen().availableGeometry()
        config.position = (screen.right() - 2, screen.bottom() - 2)
        window = self.make(config=config)
        self.assertNotEqual(
            (window.x(), window.y()),
            (screen.right() - 2, screen.bottom() - 2),
        )

    def test_moving_to_the_corner_saves(self):
        config = self.temp_config()
        window = self.make(config=config)
        window.move(50, 50)
        window.move_to_corner()
        self.assertEqual(config.position, (window.x(), window.y()))


class TestLeavingWithTheSessions(BaseWindow):
    """The widget arrives with the work session and leaves with it.

    Whether everyone is gone is the manager's business; ending the program is
    the window's, because it is the one holding the application.
    """

    def test_it_ends_the_program_once_everyone_is_gone(self):
        window = self.make()
        ended = []
        window.quit = lambda: ended.append(True)
        window.manager.abandoned = lambda: True
        window._on_tick()
        self.assertEqual(ended, [True], "the widget outlived its sessions")

    def test_it_stays_while_the_manager_says_so(self):
        window = self.make()
        ended = []
        window.quit = lambda: ended.append(True)
        window.manager.abandoned = lambda: False
        window._on_tick()
        self.assertEqual(ended, [])


class TestDragging(BaseWindow):
    """The drag animation says what *you* are doing, not what Claude is doing.

    That is why it lives on the window and never reaches the `StateManager`:
    anything asking the widget what the session is up to has to keep getting an
    honest answer while the dragon is being carried across the desk.
    """

    def _press(self, window):
        at = QPointF(0, 0)
        window.mousePressEvent(QMouseEvent(
            QEvent.MouseButtonPress, at, at,
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))

    def _move(self, window, x, y):
        at = QPointF(x, y)
        window.mouseMoveEvent(QMouseEvent(
            QEvent.MouseMove, at, at,
            Qt.NoButton, Qt.LeftButton, Qt.NoModifier))

    def _release(self, window):
        at = QPointF(0, 0)
        window.mouseReleaseEvent(QMouseEvent(
            QEvent.MouseButtonRelease, at, at,
            Qt.LeftButton, Qt.NoButton, Qt.NoModifier))

    def _busy(self):
        """A window with the session mid-thought, on screen and in the truth."""
        window = self.make()
        window.show()
        window.manager.set_state(st.THINKING)
        window._show(st.THINKING)
        return window

    def test_dragging_shows_the_drag_animation(self):
        window = self._busy()
        self._press(window)
        self._move(window, 30, 30)
        self.assertEqual(window.engine.state, st.DRAGGED)

    def test_it_never_reaches_the_truth(self):
        window = self._busy()
        self._press(window)
        self._move(window, 30, 30)
        self.assertEqual(window.manager.state, st.THINKING,
                         "the drag rewrote what the session was doing")

    def test_a_plain_click_does_not_trigger_it(self):
        # Pressing and letting go without moving is a click, not a drag: firing
        # the animation there would make every right-click-adjacent miss flash.
        window = self._busy()
        self._press(window)
        # Checked here and not after the release: by then the return to the
        # truth would have hidden the flash, and this test would pass while the
        # avatar blinked on every click.
        self.assertEqual(window.engine.state, st.THINKING,
                         "it fired on the press, before any movement")
        self._release(window)
        self.assertEqual(window.engine.state, st.THINKING)

    def test_letting_go_returns_to_the_session(self):
        window = self._busy()
        self._press(window)
        self._move(window, 30, 30)
        self._release(window)
        self.assertEqual(window.engine.state, st.THINKING)

    def test_the_clock_does_not_steal_it_mid_drag(self):
        """Without the guard the very next tick paints over the drag.

        The truth here is `done` on purpose: it is one of the states allowed to
        cut in without waiting for the current animation to finish. With any
        other one the minimum hold would protect the drag by accident and this
        test would pass while the guard was missing.
        """
        window = self._busy()
        self._press(window)
        self._move(window, 30, 30)
        window.manager.set_state(st.DONE)
        window._on_tick()
        self.assertEqual(window.engine.state, st.DRAGGED)


class TestStaysOnScreen(BaseWindow):
    """Dragging can never take the character past the edge of the screen.

    The limits apply to the drawing, not to the window: a sprite sits on a
    roomier canvas, so the window is allowed to hang off the edge by exactly
    the transparent room around the character.
    """

    def screen_of(self, window):
        return QGuiApplication.screenAt(QCursor.pos()) or window.screen()

    def drawn(self, window, placed):
        """Where the visible pixels land for a window placed at `placed`."""
        pad_left, pad_top, pad_right, pad_bottom = window.engine.padding_px
        side = window.engine.canvas_px
        return (
            placed.x() + pad_left,
            placed.y() + pad_top,
            placed.x() + side - 1 - pad_right,
            placed.y() + side - 1 - pad_bottom,
        )

    def test_the_drawing_reaches_the_left_and_top_edges(self):
        window = self.make(side=16, padding=4)
        placed = window.inside_screen(QPoint(-5000, -5000))
        full = self.screen_of(window).geometry()
        left, top, _right, _bottom = self.drawn(window, placed)
        self.assertEqual(left, full.left())
        self.assertEqual(top, full.top())

    def test_the_drawing_reaches_the_right_edge(self):
        window = self.make(side=16, padding=4)
        placed = window.inside_screen(QPoint(50_000, 0))
        full = self.screen_of(window).geometry()
        _left, _top, right, _bottom = self.drawn(window, placed)
        self.assertEqual(right, full.right())

    def test_downwards_it_rests_on_the_taskbar(self):
        """Not the monitor's edge: an avatar behind the taskbar is unreachable."""
        window = self.make(side=16, padding=4)
        placed = window.inside_screen(QPoint(0, 50_000))
        screen = self.screen_of(window)
        floor = min(screen.geometry().bottom(), screen.availableGeometry().bottom())
        _left, _top, _right, bottom = self.drawn(window, placed)
        self.assertEqual(bottom, floor)

    def test_a_transparent_canvas_may_hang_off_the_edge(self):
        """The window goes past the border; only the character has to stay in."""
        window = self.make(side=16, padding=4)
        placed = window.inside_screen(QPoint(-5000, -5000))
        full = self.screen_of(window).geometry()
        self.assertLess(placed.x(), full.left())
        self.assertLess(placed.y(), full.top())

    def test_a_spot_already_on_screen_is_left_alone(self):
        window = self.make(side=16, padding=4)
        full = self.screen_of(window).geometry()
        inside = QPoint(full.left() + 100, full.top() + 100)
        self.assertEqual(window.inside_screen(inside), inside)

    def test_dragging_off_screen_keeps_the_character_visible(self):
        window = self.make(side=16, padding=4)
        window.show()
        at = QPointF(0, 0)
        window.mousePressEvent(QMouseEvent(
            QEvent.MouseButtonPress, at, at,
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        far = QPointF(-9999, 9999)
        window.mouseMoveEvent(QMouseEvent(
            QEvent.MouseMove, far, far,
            Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        screen = self.screen_of(window)
        full = screen.geometry()
        floor = min(full.bottom(), screen.availableGeometry().bottom())
        left, top, right, bottom = self.drawn(window, window.frameGeometry().topLeft())
        self.assertGreaterEqual(left, full.left())
        self.assertGreaterEqual(top, full.top())
        self.assertLessEqual(right, full.right())
        self.assertLessEqual(bottom, floor)

    def test_a_sprite_with_no_margin_is_bounded_by_the_window(self):
        """With nothing transparent around it, drawing and window coincide."""
        window = self.make(side=16, padding=0)
        self.assertEqual(window.engine.padding_px, (0, 0, 0, 0))
        placed = window.inside_screen(QPoint(-5000, -5000))
        full = self.screen_of(window).geometry()
        self.assertEqual(placed.x(), full.left())
        self.assertEqual(placed.y(), full.top())


class TestVisibility(BaseWindow):
    def test_hiding_takes_it_off_screen(self):
        window = self.make()
        window.show()
        self.assertTrue(window.isVisible())
        window.hide_for(15)
        self.assertFalse(window.isVisible())

    def test_hiding_is_not_closing(self):
        # Closing kills the process through WA_QuitOnClose; hiding must not.
        # Had it closed, there would be nothing left to bring back.
        window = self.make()
        window.show()
        window.hide_for(15)
        self.assertFalse(window.isVisible())
        window.show_again()
        self.assertTrue(window.isVisible())

    def test_the_deadline_is_armed_with_what_was_asked(self):
        window = self.make()
        window.show()
        window.hide_for(15)
        self.assertTrue(window._unhide.isActive())
        self.assertEqual(window._unhide.interval(), 15 * 60_000)

    def test_asking_again_replaces_the_deadline(self):
        # Two stacked deadlines would mean the first one pops the avatar back
        # up in the middle of the second.
        window = self.make()
        window.show()
        window.hide_for(240)
        window.hide_for(15)
        self.assertEqual(window._unhide.interval(), 15 * 60_000)

    def test_the_deadline_brings_it_back_on_its_own(self):
        # The whole point of the deadline: with no tray icon, nobody can
        # rescue a hidden avatar by hand.
        window = self.make()
        window.show()
        window.hide_for(0)
        self.assertFalse(window.isVisible())
        _app.processEvents()
        self.assertTrue(window.isVisible())

    def test_coming_back_drops_the_deadline(self):
        window = self.make()
        window.show()
        window.hide_for(15)
        window.show_again()
        self.assertFalse(window._unhide.isActive())


class TestMenu(BaseWindow):
    def test_the_menu_can_be_repopulated(self):
        from PySide6.QtWidgets import QMenu

        window = self.make()
        menu = QMenu()
        window.populate_menu(menu)
        first = len(menu.actions())
        window.populate_menu(menu)
        self.assertEqual(len(menu.actions()), first, "the menu was duplicated")

    def test_the_menu_is_split_into_three_blocks(self):
        # The order is a decision, not an accident: who the avatar is, where it
        # sits and when it shows, and leaving. Quit stays alone in its block so
        # it is never a neighbour of something you click often.
        window = self.make()
        window.show()
        menu = window.build_menu(window)

        blocks: list[list[str]] = [[]]
        for action in menu.actions():
            if action.isSeparator():
                blocks.append([])
            else:
                blocks[-1].append(action.text())

        self.assertEqual(len(blocks), 3, f"expected three blocks, got {blocks}")
        self.assertEqual(blocks[0], ["Force state"])
        self.assertEqual(
            blocks[1], ["Hide for", "Move to corner", "Reload assets"]
        )
        self.assertEqual(blocks[2], ["Quit"])

    def test_the_submenus_outlive_a_look_at_them(self):
        """Regression: `menu.addMenu(title)` ties the submenu's life to Python.

        Reaching for a submenu through `menu.actions()` and letting that
        temporary action wrapper go was enough for Qt to destroy the submenu,
        leaving the entry pointing at nothing.
        """
        window = self.make()
        window.populate_menu(window._menu)

        def reach(name):
            # The action wrapper is temporary on purpose: that is what used to
            # take the submenu down with it.
            return next(
                a for a in window._menu.actions() if a.text() == name
            ).menu()

        for name in ("Force state", "Hide for"):
            sub = reach(name)
            gc.collect()
            try:
                found = sub.actions()
            except RuntimeError:
                self.fail(f"{name!r} was destroyed just by looking at it")
            self.assertTrue(found, f"{name!r} came back empty")

    def _hide_submenu(self, menu):
        return next(a for a in menu.actions() if a.text() == "Hide for").menu()

    def test_the_hide_submenu_offers_the_deadlines(self):
        window = self.make()
        window.show()
        menu = window.build_menu(window)
        self.assertEqual(
            [a.text() for a in self._hide_submenu(menu).actions()],
            [label for label, _ in menu_mod.HIDE_OPTIONS],
        )

    def test_picking_a_deadline_hides_for_exactly_that_long(self):
        # The label and the window have to agree on the number: a menu that
        # says "1 hour" and hides for fifteen minutes is worse than no menu.
        window = self.make()
        window.show()
        menu = window.build_menu(window)
        for action, (_label, minutes) in zip(
            self._hide_submenu(menu).actions(), menu_mod.HIDE_OPTIONS
        ):
            action.trigger()
            self.assertFalse(window.isVisible())
            self.assertEqual(window._unhide.interval(), minutes * 60_000)
            window.show_again()

    def test_a_single_character_hides_the_submenu(self):
        window = self.make()
        menu = window.build_menu(window)
        self.assertNotIn("Character", [a.text() for a in menu.actions()])


class TestMinimumHold(BaseWindow):
    """A state has to be seen before another one replaces it."""

    def with_states(self) -> AvatarWindow:
        return self.make(
            states=("idle", "thinking", "working", "waiting", "done")
        )

    def test_a_brief_state_does_not_overwrite_the_previous_one(self):
        w = self.with_states()
        w.force_state(st.WORKING)
        w.manager.set_state(st.THINKING)
        w._on_tick()
        self.assertEqual(w.engine.state, st.WORKING, "replaced too early")

    def test_once_the_minimum_is_met_it_applies(self):
        w = self.with_states()
        w.force_state(st.WORKING)
        w.manager.set_state(st.THINKING)
        w._smoothing.shown_since -= 999  # as if the time had already passed
        w._on_tick()
        self.assertEqual(w.engine.state, st.THINKING)

    def test_it_jumps_to_the_current_truth_not_the_one_in_between(self):
        # No queue: what gets skipped, gets skipped. That is what keeps the
        # avatar from falling behind without bound during a burst.
        w = self.with_states()
        w.force_state(st.WORKING)
        w.manager.set_state(st.THINKING)   # in between, never shown
        w._on_tick()
        w.manager.set_state(st.IDLE)       # the truth once the minimum is met
        w._smoothing.shown_since -= 999
        w._on_tick()
        self.assertEqual(w.engine.state, st.IDLE)

    def test_waiting_comes_in_immediately(self):
        # It announces that Claude needs you: holding it back ruins what makes
        # it useful.
        w = self.with_states()
        w.force_state(st.WORKING)
        w.manager.set_state(st.WAITING)
        w._on_tick()
        self.assertEqual(w.engine.state, st.WAITING)

    def test_the_transients_come_in_immediately(self):
        for state in sorted(st.ONE_SHOT):
            w = self.with_states()
            w.force_state(st.WORKING)
            w.manager.set_state(state)
            w._on_tick()
            self.assertEqual(w.engine.state, state, f"{state} was held back")

    def test_a_one_shot_asks_for_one_cycle_and_not_several(self):
        # It freezes on the last frame: asking for two cycles would show
        # nothing new.
        w = self.with_states()
        w.force_state(st.DONE)
        one = w.engine.duration_ms(st.DONE) / 1000.0
        self.assertAlmostEqual(w._smoothing.minimum_hold(), one, places=3)

    def test_a_loop_asks_for_several_cycles(self):
        w = self.with_states()
        w.force_state(st.WORKING)
        one = w.engine.duration_ms(st.WORKING) / 1000.0
        self.assertAlmostEqual(
            w._smoothing.minimum_hold(),
            one * smoothing_mod.MIN_CYCLES,
            places=3,
        )

    def test_forcing_from_the_menu_is_immediate(self):
        # This is the menu used to review sprites: waiting would defeat it.
        w = self.with_states()
        w.force_state(st.WORKING)
        w.force_state(st.THINKING)
        self.assertEqual(w.engine.state, st.THINKING)

    def test_at_zero_it_goes_back_to_instant(self):
        original = smoothing_mod.MIN_CYCLES
        try:
            smoothing_mod.MIN_CYCLES = 0
            w = self.with_states()
            w.force_state(st.WORKING)
            w.manager.set_state(st.THINKING)
            w._on_tick()
            self.assertEqual(w.engine.state, st.THINKING)
        finally:
            smoothing_mod.MIN_CYCLES = original

    def test_the_ephemeral_ones_claim_no_screen_time(self):
        # Protecting `idle` would make the avatar take almost two seconds to
        # react to a prompt; protecting `thinking` would steal screen time
        # from the tool animations.
        w = self.with_states()
        for ephemeral in (st.IDLE, st.THINKING):
            w.force_state(ephemeral)
            self.assertEqual(
                w._smoothing.minimum_hold(), 0.0, f"{ephemeral} holds"
            )

    def test_a_prompt_shows_up_instantly(self):
        w = self.with_states()
        w.force_state(st.IDLE)
        w.manager.set_state(st.THINKING)
        w._on_tick()
        self.assertEqual(w.engine.state, st.THINKING)

    def test_a_tool_replaces_thinking_with_no_delay(self):
        w = self.with_states()
        w.force_state(st.THINKING)
        w.manager.set_state(st.WORKING)
        w._on_tick()
        self.assertEqual(w.engine.state, st.WORKING)

    def test_with_no_sprites_it_does_not_get_stuck(self):
        # Zero duration: it must not end up holding forever.
        w = self.make()
        w.manager.set_state(st.THINKING)
        w._smoothing.shown_since -= 999
        w._on_tick()
        self.assertEqual(w.engine.state, st.THINKING)


if __name__ == "__main__":
    unittest.main(verbosity=2)
