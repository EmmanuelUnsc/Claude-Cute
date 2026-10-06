"""Overlay window: frameless, translucent, always-on-top and draggable."""

from __future__ import annotations

import sys
import time

from PySide6.QtCore import Qt, QPoint, QRect, QTimer, QVariantAnimation
from PySide6.QtGui import QCursor, QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from .animation_engine import AnimationEngine
from . import entrance
from . import menu as _menu
from .config import Config
from .smoothing import Smoothing
from .state_manager import StateManager
from .states import DRAGGED, FALLING, LANDING

MARGIN = 24  # gap from the edge of the screen

# Seconds between reclaiming the top of the stack.
ON_TOP_EVERY = 3.0


def _assert_topmost(window_id: int) -> None:
    """Puts the window back at the top of the always-on-top band.

    Windows sets "topmost" once, and the last topmost window to be activated
    wins: click the taskbar and it covers an avatar nobody has touched since
    startup. `SWP_NOACTIVATE` matters, or this would steal focus from whatever
    you are typing in. Elsewhere the window manager keeps the flag, so it is a
    no-op.
    """
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    set_window_pos = ctypes.windll.user32.SetWindowPos
    set_window_pos.argtypes = (
        wintypes.HWND, wintypes.HWND,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.UINT,
    )
    hwnd_topmost = wintypes.HWND(-1)
    swp_nosize, swp_nomove, swp_noactivate = 0x0001, 0x0002, 0x0010
    set_window_pos(
        window_id, hwnd_topmost, 0, 0, 0, 0,
        swp_nosize | swp_nomove | swp_noactivate,
    )


class AvatarWindow(QWidget):
    def __init__(
        self,
        manager: StateManager,
        engine: AnimationEngine,
        config: Config | None = None,
    ) -> None:
        super().__init__()
        self.manager = manager
        self.engine = engine
        self.config = config
        self._drag_offset: QPoint | None = None
        self._dragging = False
        self._frame: QPixmap | None = engine.current_frame()
        self._smoothing = Smoothing(engine)
        self._on_top_at = time.monotonic()
        # Where the entrance lands, while it is playing: the dive and then
        # the landing.
        self._falling_to: QPoint | None = None
        self._fall_distance = 0.0
        # One menu, refilled on each opening rather than recreated.
        self._menu = QMenu(self)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool  # keeps it out of the taskbar
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Qt.Tool leaves this off, and without it closing the window would keep
        # the process alive holding the port.
        self.setAttribute(Qt.WA_QuitOnClose, True)
        # Size comes from the character, so any resolution or scale fits.
        self.resize(engine.canvas_px, engine.canvas_px)
        self.restore_position()

        # One timer drives both the frame advance and the state polling.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(engine.interval_ms())

        # Brings the avatar back when a "Hide for" runs out.
        self._unhide = QTimer(self)
        self._unhide.setSingleShot(True)
        self._unhide.timeout.connect(self.show_again)

        # The entrance moves the window at the screen's own pace: the frame
        # timer runs at 100-300 ms and would make the fall stutter.
        self._fall = QVariantAnimation(self)
        self._fall.valueChanged.connect(self._fall_step)
        self._fall.finished.connect(self._impact)
        # Hands the screen back once the landing has played.
        self._arrival = QTimer(self)
        self._arrival.setSingleShot(True)
        self._arrival.timeout.connect(self._arrived)

    # --- animation loop -----------------------------------------------------

    def _on_tick(self) -> None:
        # The manager reports that every session is gone; ending the program
        # is the window's call, since it owns the application.
        if self.manager.abandoned():
            self.quit()
            return
        truth = self.manager.tick()
        # While dragging or dropping in, the screen shows that; the truth keeps
        # advancing underneath and is picked up again at the end.
        if not self._dragging and self._falling_to is None:
            if truth != self.engine.state and self._smoothing.can_replace(truth):
                self._show(truth)
        self._frame = self.engine.advance()
        self.update()
        if time.monotonic() - self._on_top_at >= ON_TOP_EVERY:
            self.stay_on_top()

    def stay_on_top(self) -> None:
        """Reclaims the top of the stack, in case something climbed over it.

        Not while the menu is open, which would end up underneath, nor while
        hidden, which would be pointless.
        """
        self._on_top_at = time.monotonic()
        if self.isVisible() and not self._menu.isVisible():
            _assert_topmost(int(self.winId()))

    def _show(self, state: str) -> None:
        self.engine.set_state(state)
        self._timer.setInterval(self.engine.interval_ms())
        self._smoothing.mark_shown()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        # No smoothing: the assets are pixel art and interpolation blurs them.
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        if self._frame is not None:
            painter.drawPixmap(self.rect(), self._frame)

    # --- interaction --------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # Caught mid-entrance: it stays where it was caught.
        if self._falling_to is not None:
            self._fall.stop()
            self._arrival.stop()
            self._falling_to = None
            self._show(self.manager.state)
        if event.button() == Qt.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            # Starts on the first real movement, so a plain click does not
            # flash the drag animation.
            if not self._dragging:
                self._dragging = True
                self._show(DRAGGED)
            self.move(
                self.inside_screen(
                    event.globalPosition().toPoint() - self._drag_offset
                )
            )

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None:
            self._drag_offset = None
            if self._dragging:
                self._dragging = False
                self._show(self.manager.state)
            # Saved on release, not on every pixel of the drag.
            self.remember_position()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self.populate_menu(self._menu)
        self._menu.exec(QCursor.pos())

    def closeEvent(self, event) -> None:  # noqa: N802
        self.remember_position()
        super().closeEvent(event)

    # --- entrance -----------------------------------------------------------

    def drop_in(self) -> None:
        """Shows the avatar arriving as a meteor that dives onto its spot.

        From above the top edge of the monitor it lands on, along a 45 degree
        line from the upper left; on impact the `landing` animation plays and
        the dragon comes out of it. Skipped when there is no room to fall or
        the system has animations turned off.
        """
        target = self.pos()
        screen = QGuiApplication.screenAt(self.geometry().center()) or self.screen()
        distance = float(target.y() - (screen.geometry().top() - self.height()))
        if distance <= 0 or not entrance.animations_enabled():
            self.show()
            return
        self._falling_to = target
        self._fall_distance = distance
        self.move(self._dive_point(distance))
        self._show(FALLING)
        self._repaint_now()
        total = entrance.fall_ms(distance)
        self._fall.setStartValue(0.0)
        self._fall.setEndValue(total)
        self._fall.setDuration(max(1, round(total)))
        self.show()
        self._fall.start()

    def _dive_point(self, height: float) -> QPoint:
        """Where the window is when the meteor is `height` above its spot."""
        return QPoint(
            self._falling_to.x() - round(height * entrance.SLANT),
            self._falling_to.y() - round(height),
        )

    def _fall_step(self, ms) -> None:
        if self._falling_to is None or self.engine.state != FALLING:
            return
        self.move(self._dive_point(entrance.height_at(float(ms), self._fall_distance)))

    def _impact(self) -> None:
        if self._falling_to is None:
            return
        self.move(self._falling_to)
        self._show(LANDING)
        self._repaint_now()
        # One extra frame on the last pose, which is her resting one, so the
        # hand-over to the truth is not a cut.
        self._arrival.start(
            self.engine.duration_ms(LANDING) + self.engine.interval_ms()
        )

    def _arrived(self) -> None:
        if self._falling_to is None:
            return
        self._falling_to = None
        self._show(self.manager.state)
        self._repaint_now()

    def _repaint_now(self) -> None:
        """Paints the current state's frame now instead of on the next tick.

        The frame clock runs at 100-300 ms; at the turns of the entrance that
        is long enough to see the wrong pose: a dragon in the sky, a meteor on
        the ground.
        """
        self._frame = self.engine.current_frame()
        self.update()

    # --- menu ---------------------------------------------------------------

    # Thin wrappers over `menu.py`, which owns the menu's contents.

    def build_menu(self, parent: QWidget | None = None) -> QMenu:
        return _menu.build_menu(self, parent)

    def populate_menu(self, menu: QMenu) -> QMenu:
        return _menu.populate_menu(menu, self)

    # --- actions ------------------------------------------------------------

    def set_character(self, name: str) -> None:
        self.engine.set_character(name)
        if self.config is not None:
            self.config.character = name
            self.config.save()
        self._apply_measurements()

    def force_state(self, state: str) -> None:
        """Shows a state right away, without waiting out the current one."""
        self.manager.set_state(state)
        self._show(state)

    def quit(self) -> None:
        """Ends the program, whether the avatar is visible or hidden.

        `close()` is not enough: a window that was never shown does not fire
        `lastWindowClosed`.
        """
        self.remember_position()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def reload_assets(self) -> None:
        """Re-reads the sprites from disk. This is what you use while drawing."""
        self.engine.reload()
        self._apply_measurements()

    def hide_for(self, minutes: float) -> None:
        """Hides the avatar and brings it back on its own when the time is up.

        Hiding always carries a deadline: it is the only way back, since there
        is no window left to right-click. Hiding is not closing, which would
        end the program.
        """
        self.setVisible(False)
        # Restarts the same single shot, so hiding again replaces the deadline
        # instead of stacking a second one.
        self._unhide.start(int(minutes * 60_000))

    def show_again(self) -> None:
        """Back on screen, and any pending deadline is dropped."""
        self._unhide.stop()
        self.setVisible(True)
        self.raise_()
        self.stay_on_top()

    def _apply_measurements(self) -> None:
        """Resizes in case the character's size or scale changed."""
        side = self.engine.canvas_px
        if side != self.width():
            self.resize(side, side)
        self._timer.setInterval(self.engine.interval_ms())
        self._frame = self.engine.current_frame()
        self.update()

    # --- position -----------------------------------------------------------

    def move_to_corner(self) -> None:
        """Bottom-right corner. Also rescues the window if it ended up off-screen.

        The gap is measured from the drawing, not from the canvas, so it looks
        the same however much transparent room a character leaves.
        """
        screen = self.screen().availableGeometry()
        side = self.engine.canvas_px
        _left, _top, pad_right, pad_bottom = self.engine.padding_px
        self.move(
            screen.right() - side + 1 + pad_right - MARGIN,
            screen.bottom() - side + 1 + pad_bottom - MARGIN,
        )
        self.remember_position()

    def inside_screen(self, position: QPoint) -> QPoint:
        """The nearest spot to `position` that keeps the character on screen.

        The limits apply to the drawing, not to the window: sprites sit on a
        square canvas with transparent room around them, so the window is
        allowed to hang off the edge by exactly as much as that room.

        Sideways and up the limit is the monitor's own edge; downwards it is
        the top of the taskbar, so the character rests on it instead of
        disappearing behind it. Measured against the screen under the cursor,
        so dragging across a multi-monitor setup still works.
        """
        screen = QGuiApplication.screenAt(QCursor.pos()) or self.screen()
        if screen is None:
            return position
        full = screen.geometry()
        side = self.engine.canvas_px
        pad_left, pad_top, pad_right, pad_bottom = self.engine.padding_px
        # The taskbar is the one edge worth respecting: an avatar behind it
        # cannot be grabbed again.
        floor = min(full.bottom(), screen.availableGeometry().bottom())

        first_x = full.left() - pad_left
        last_x = full.right() - side + 1 + pad_right
        first_y = full.top() - pad_top
        last_y = floor - side + 1 + pad_bottom
        # `max` guards a screen smaller than the avatar, where the two limits
        # would otherwise cross over.
        return QPoint(
            min(max(position.x(), first_x), max(first_x, last_x)),
            min(max(position.y(), first_y), max(first_y, last_y)),
        )

    def restore_position(self) -> None:
        """Goes back where it was, if that spot is still visible.

        A disconnected monitor can leave saved coordinates that no longer land
        on any screen.
        """
        saved = self.config.position if self.config is not None else None
        if saved is not None and self._is_visible(*saved):
            self.move(*saved)
        else:
            self.move_to_corner()

    def remember_position(self) -> None:
        if self.config is None:
            return
        # Mid-entrance the window is somewhere in the air; its spot is where
        # it is headed.
        point = self._falling_to or self.frameGeometry().topLeft()
        self.config.position = (point.x(), point.y())
        self.config.save()

    def _is_visible(self, x: int, y: int) -> bool:
        """Whether a window at (x, y) would land inside some screen."""
        side = self.engine.canvas_px
        # A decent chunk, not one pixel: a sliver cannot be grabbed to drag.
        minimum = max(1, side // 4)
        proposed = QRect(x, y, side, side)
        for screen in QGuiApplication.screens():
            visible = proposed.intersected(screen.geometry())
            if visible.width() >= minimum and visible.height() >= minimum:
                return True
        return False
