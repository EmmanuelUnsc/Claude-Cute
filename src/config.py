"""Preferences that survive between launches: position, character and port.

Stored in a `config.json` next to the project, so the program never touches
anything outside its own folder.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

FILENAME = "config.json"


class Config:
    """Reads and writes the preferences, tolerating a missing or broken file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._data: dict[str, Any] = {}

    # --- disk ---------------------------------------------------------------

    def load(self) -> Config:
        try:
            # utf-8-sig so a BOM left by a Windows editor does not break parsing.
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            data = {}
        self._data = data if isinstance(data, dict) else {}
        return self

    def save(self) -> bool:
        """Writes atomically, via a temporary file. Returns whether it worked."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=self.path.name,
                suffix=".tmp",
                delete=False,
            ) as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
                temporary = Path(f.name)
            os.replace(temporary, self.path)
            return True
        except OSError:
            return False

    # --- position -----------------------------------------------------------

    @property
    def position(self) -> tuple[int, int] | None:
        value = self._data.get("position")
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return None
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return None

    @position.setter
    def position(self, xy: tuple[int, int] | None) -> None:
        if xy is None:
            self._data.pop("position", None)
        else:
            self._data["position"] = [int(xy[0]), int(xy[1])]

    # --- character ----------------------------------------------------------

    @property
    def character(self) -> str | None:
        value = self._data.get("character")
        return value if isinstance(value, str) and value else None

    @character.setter
    def character(self, name: str | None) -> None:
        if name:
            self._data["character"] = str(name)
        else:
            self._data.pop("character", None)

    # --- port ---------------------------------------------------------------

    @property
    def port(self) -> int | None:
        """The server's port, or `None` to use the usual one.

        `hooks/notify.py` reads this same file, so both ends stay in step.
        Values outside 1024-65535 are ignored.
        """
        try:
            value = int(self._data["port"])
        except (KeyError, TypeError, ValueError):
            return None
        return value if 1024 <= value <= 65535 else None

    @port.setter
    def port(self, value: int | None) -> None:
        if value is None:
            self._data.pop("port", None)
        else:
            self._data["port"] = int(value)
