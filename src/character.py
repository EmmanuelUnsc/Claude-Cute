"""A character's data: what its `character.json` says, already validated.

A character is a folder in `assets/` holding one subfolder of sprites per state,
plus an optional `character.json`:

    {
      "name": "Dragon",
      "scale": 2,
      "ms_per_frame": { "idle": 220, "working": 100 },
      "loop_from":    { "dragged": 6 }
    }

Every key is optional and every bad value falls back to its default, so a typo
never keeps the avatar from starting.
"""

from __future__ import annotations

import json
from pathlib import Path

from .states import STATES, ancestors

# Default speeds in milliseconds per frame. A state with no entry of its own
# inherits the one from its nearest ancestor, just like sprites do.
DEFAULT_FRAME_MS_BY_STATE = {
    "idle": 220,
    "idle-sleep": 320,
    "thinking": 120,
    "working": 100,
    "waiting": 140,
    "done": 160,
    "error": 110,
    "wake": 150,
    "sleep": 200,
    "compacting": 130,
}
DEFAULT_FRAME_MS = 150

SHEET = "character.json"
DEFAULT_SCALE = 2


def available_characters(assets_dir: Path) -> list[str]:
    """Folder names of the characters found in `assets/`.

    A character is a subfolder holding a `character.json` or, failing that, at
    least one state folder.
    """
    assets_dir = Path(assets_dir)
    if not assets_dir.is_dir():
        return []
    found = []
    for child in sorted(assets_dir.iterdir()):
        if not child.is_dir():
            continue
        if (child / SHEET).is_file() or any((child / s).is_dir() for s in STATES):
            found.append(child.name)
    return found


class Character:
    """A character's data, read from disk and already validated."""

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        sheet = self._read(self.folder / SHEET)
        self.name = sheet.get("name")
        self.scale = self._scale(sheet)
        # Speeds and loop points are kept raw and checked one at a time, so a
        # broken entry cannot take the others down with it.
        speeds = sheet.get("ms_per_frame")
        self._speeds = speeds if isinstance(speeds, dict) else {}
        loops = sheet.get("loop_from")
        self._loops = loops if isinstance(loops, dict) else {}

    @staticmethod
    def _read(path: Path) -> dict:
        """The sheet's JSON, or an empty dict if it could not be read."""
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _scale(sheet: dict) -> int:
        """Magnification. Whole numbers only: fractional blurs the pixel art."""
        try:
            scale = int(sheet.get("scale", DEFAULT_SCALE))
        except (TypeError, ValueError):
            scale = DEFAULT_SCALE
        return max(1, scale)

    def loop_from(self, state: str, frames: int) -> int | None:
        """Index the loop goes back to, or `None` if there is no such loop.

        Some animations have an entry: a few frames that play once and then a
        shorter loop that runs for as long as the state lasts. In the sheet:

            "loop_from": { "dragged": 6 }

        Counted from 1, like the file names. A number out of range is ignored,
        so the animation simply loops from the start.
        """
        try:
            first = int(self._loops[state])
        except (KeyError, TypeError, ValueError):
            return None
        return first - 1 if 1 <= first <= frames else None

    def ms_per_frame(self, state: str) -> int:
        """The state's speed, walking up the ancestors until one is found."""
        for candidate in ancestors(state):
            if candidate in self._speeds:
                try:
                    return int(self._speeds[candidate])
                except (TypeError, ValueError):
                    pass
            if candidate in DEFAULT_FRAME_MS_BY_STATE:
                return DEFAULT_FRAME_MS_BY_STATE[candidate]
        return DEFAULT_FRAME_MS
