"""Overlay window: frameless, translucent, always-on-top and draggable."""

from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, QRect, QTimer
from PySide6.QtGui import QCursor, QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from .animation_engine import AnimationEngine
from . import menu as _menu
from .config import Config
from .smoothing import Smoothing
from .state_manager import StateManager
from .states import DRAGGED

MARGIN = 24  # gap from the edge of the screen


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

    # --- animation loop -----------------------------------------------------

    def _on_tick(self) -> None:
        # The manager reports that every session is gone; ending the program
        # is the window's call, since it owns the application.
        if self.manager.abandoned():
            self.quit()
            return
        truth = self.manager.tick()
        # While dragging, the screen shows the drag; the truth keeps advancing
        # underneath and is picked up again on release.
        if not self._dragging:
            if truth != self.engine.state and self._smoothing.can_replace(truth):
                self._show(truth)
        self._frame = self.engine.advance()
        self.update()

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
        point = self.frameGeometry().topLeft()
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
