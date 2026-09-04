"""Loads a character's sprites and hands out the frame that should be shown."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect
from PySide6.QtGui import QPixmap, QRegion

from .character import Character, available_characters
from .states import IDLE, STATES, TRANSIENTS, ONE_SHOT, ancestors

DEFAULT_FRAME_PX = 128


class AnimationEngine:
    """Keeps the frame sequences and advances the index of the current one.

    Sprites live in `assets/<character>/<state>/frame_*.png`. A state with no
    folder of its own is not an error: it walks up its ancestors until it finds
    frames, so a character can be drawn a few states at a time.
    """

    def __init__(self, assets_dir: Path, character: str | None = None) -> None:
        self.assets_dir = Path(assets_dir)
        self._folder = character or self._default_character()
        self._frames: dict[str, list[QPixmap]] = {}
        self._state = IDLE
        self._resolved = IDLE
        self._index = 0
        self.reload()

    # --- character ----------------------------------------------------------

    def _default_character(self) -> str | None:
        available = available_characters(self.assets_dir)
        return available[0] if available else None

    @property
    def character(self) -> str | None:
        """Folder of the active character, or None if `assets/` is flat."""
        return self._folder

    @property
    def character_name(self) -> str:
        """Readable name, from `character.json` or from the folder."""
        return self._character.name or self._folder or "unnamed"

    def characters(self) -> list[str]:
        return available_characters(self.assets_dir)

    def set_character(self, character: str) -> None:
        if character == self._folder:
            return
        self._folder = character
        self.reload()

    @property
    def _root(self) -> Path:
        """The folder the active character's states come from.

        With no character subfolders, `assets/` is used directly, which keeps
        the flat layout working.
        """
        if self._folder:
            return self.assets_dir / self._folder
        return self.assets_dir

    # --- loading ------------------------------------------------------------

    def reload(self) -> None:
        self._character = Character(self._root)
        self._frames = {state: self._load(state) for state in STATES}
        self._drawn = self._drawn_areas()
        self._resolved = self._resolve(self._state)
        self._index = 0

    def _drawn_areas(self) -> dict[str, QRect]:
        """Where the visible pixels sit, per state.

        Sprites are drawn on a square canvas with room to spare, so the window
        is wider than the character. Anything positioning the avatar against an
        edge has to know where the drawing actually starts — and it is measured
        per state, because an animation that sticks a flame or a magnifier out
        to one side would otherwise decide the margin for every other one.
        """
        areas = {}
        for state, frames in self._frames.items():
            box = QRect()
            for pixmap in frames:
                box = box.united(QRegion(pixmap.mask()).boundingRect())
            if not box.isEmpty():
                areas[state] = box
        return areas

    def _load(self, state: str) -> list[QPixmap]:
        folder = self._root / state
        if not folder.is_dir():
            return []
        frames = []
        for path in sorted(folder.glob("frame_*.png")):
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                frames.append(pixmap)
        return frames

    def _resolve(self, state: str) -> str:
        """First ancestor of the state that has frames loaded."""
        for candidate in ancestors(state):
            if self._frames.get(candidate):
                return candidate
        return IDLE

    # --- measurements -------------------------------------------------------

    @property
    def scale(self) -> int:
        return self._character.scale

    @property
    def frame_px(self) -> int:
        """Canvas side, read from the sprites instead of assumed."""
        for frames in self._frames.values():
            if frames:
                return frames[0].width()
        return DEFAULT_FRAME_PX

    @property
    def canvas_px(self) -> int:
        return self.frame_px * self.scale

    @property
    def padding_px(self) -> tuple[int, int, int, int]:
        """Transparent room around the character at rest.

        Left, top, right, bottom, in screen pixels, so it can be applied
        straight to a position. Measured on the resting pose and not on the
        animation of the moment: that is the silhouette the avatar shows almost
        all the time and the one it returns to, so an edge lines up with it
        instead of shifting every time the state changes.
        """
        drawn = self._drawn.get(self._resolve(IDLE))
        if drawn is None or drawn.isEmpty():
            return (0, 0, 0, 0)
        side, scale = self.frame_px, self.scale
        return (
            drawn.left() * scale,
            drawn.top() * scale,
            (side - 1 - drawn.right()) * scale,
            (side - 1 - drawn.bottom()) * scale,
        )

    # --- state --------------------------------------------------------------

    @property
    def state(self) -> str:
        """The logical state asked for, with or without sprites of its own."""
        return self._state

    @property
    def resolved_state(self) -> str:
        """The state whose sprites are actually being shown."""
        return self._resolved

    def set_state(self, state: str) -> None:
        if state == self._state:
            # Repeating a one-shot state plays it again from the start.
            if state in ONE_SHOT:
                self._index = 0
            return
        self._state = state
        resolved = self._resolve(state)
        # Two states resolving to the same sprites do not restart the animation.
        if resolved != self._resolved:
            self._resolved = resolved
            self._index = 0

    def plays_once(self) -> bool:
        """Whether the current animation is a one-shot.

        Only when the state has sprites of its own; an inherited animation
        loops.
        """
        return self._state in ONE_SHOT and self._resolved == self._state

    def finished(self) -> bool:
        """Whether a one-shot animation has already reached its end."""
        frames = self._frames.get(self._resolved) or []
        return bool(frames) and self.plays_once() and self._index >= len(frames) - 1

    def interval_ms(self, state: str | None = None) -> int:
        """Milliseconds per frame of the animation being shown.

        The pace comes from the animation on screen, so an inherited state runs
        at its ancestor's speed.
        """
        return self._character.ms_per_frame(self._resolve(state or self._state))

    # --- frames -------------------------------------------------------------

    def current_frame(self) -> QPixmap | None:
        frames = self._frames.get(self._resolved) or []
        if not frames:
            return None
        return frames[self._index % len(frames)]

    def advance(self) -> QPixmap | None:
        frames = self._frames.get(self._resolved) or []
        if not frames:
            return None
        self._index += 1
        if self._index < len(frames):
            return self.current_frame()

        # Past the last frame, where it goes back to tells the three shapes
        # apart: entry + loop (`loop_from` in the sheet), one-shot (freezes on
        # the last frame) or plain loop (starts over).
        loop_start = self._character.loop_from(self._resolved, len(frames))
        if loop_start is not None:
            self._index = loop_start
        elif self.plays_once():
            self._index = len(frames) - 1
        else:
            self._index = 0
        return self.current_frame()

    # --- diagnostics --------------------------------------------------------

    def missing_states(self) -> list[str]:
        """States with no frames of their own: they fall back to an ancestor."""
        return [state for state in STATES if not self._frames.get(state)]

    def available_states(self) -> list[str]:
        """States with their own sprites in the current character."""
        return [state for state in STATES if self._frames.get(state)]

    def duration_ms(self, state: str) -> int:
        """How long one full pass of a state's animation takes."""
        resolved = self._resolve(state)
        frames = self._frames.get(resolved) or []
        return len(frames) * self.interval_ms(state)

    def frozen_states(
        self, margin_ms: int = 1000
    ) -> list[tuple[str, int, float]]:
        """One-shot states that sit too long on their last frame.

        The inverse of `truncated_states`: the animation ends well before the
        state expires, so the final pose is held longer than looks deliberate.
        """
        frozen = []
        for state, (seconds, _next_state) in TRANSIENTS.items():
            frames = self._frames.get(state)
            if not frames:
                continue  # inherits: it loops, so nothing freezes
            if self._character.loop_from(state, len(frames)) is not None:
                continue  # has a moving tail: nothing freezes
            spare = seconds * 1000 - self.duration_ms(state)
            if spare > margin_ms:
                frozen.append((state, int(spare), seconds))
        return frozen

    def truncated_states(self) -> list[tuple[str, int, float]]:
        """One-shot states whose animation never gets seen in full.

        Happens when frames are added without adjusting the state's expiry in
        `TRANSIENTS`.
        """
        truncated = []
        for state, (seconds, _next_state) in TRANSIENTS.items():
            if not self._frames.get(state):
                continue  # inherits: it loops, so nothing gets cut
            duration = self.duration_ms(state)
            if duration > seconds * 1000:
                truncated.append((state, duration, seconds))
        return truncated
