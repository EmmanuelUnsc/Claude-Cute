"""Registers the hooks by hand, for the Claude desktop app.

The plugin is the normal way in, and in a terminal or an IDE it covers
everything. The desktop app does not reliably run the hooks a plugin declares
(claude-code#34573), so there the dragon neither starts nor reacts. Running
this once registers the same hooks in `~/.claude/settings.json`, which the
desktop app does run.

    py install.py          register
    py uninstall.py        undo it

It sits alongside the plugin rather than replacing it: the launcher does
nothing when a widget is already up, so nothing is duplicated. Everything else
in the settings file is left exactly as it was, and a backup is written before
anything changes.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

SETTINGS = Path.home() / ".claude" / "settings.json"

# The events that tell the widget what is happening. A plugin's `hooks.json`
# fails to deliver these in the desktop app.
EVENTS = (
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PostToolBatch",
    "PermissionRequest",
    "PermissionDenied",
)

# The events that start the widget. `launch.py` does nothing when one is
# already running, so registering these alongside the plugin is harmless.
LAUNCH_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
)

# Events that take a `matcher`; the others reject one.
TAKES_MATCHER = {
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PermissionRequest",
    "PermissionDenied",
    "SessionStart",
}

HOOKS = Path(__file__).resolve().parent / "hooks"
NOTIFY = HOOKS / "notify.py"
LAUNCH = HOOKS / "launch.py"


def read_settings() -> dict:
    """The settings file as a dict, or `{}` if there is none yet.

    A file that exists but cannot be parsed stops the install: overwriting it
    would throw away whatever the user has in there.
    """
    if not SETTINGS.is_file():
        return {}
    try:
        text = SETTINGS.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise SystemExit(f"cannot read {SETTINGS}: {exc}")
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise SystemExit(
            f"{SETTINGS} is not valid JSON ({exc}).\n"
            "Nothing was changed. Fix the file, or move it aside, and try again."
        )
    if not isinstance(data, dict):
        raise SystemExit(f"{SETTINGS} does not hold a JSON object. Nothing changed.")
    return data


def is_ours(entry: dict) -> bool:
    """Whether a hook entry is one of ours, from this copy or an older one."""
    if entry.get("type") != "command":
        return False
    args = entry.get("args")
    if not isinstance(args, list):
        return False
    return any(
        isinstance(a, str) and Path(a).name in ("notify.py", "launch.py")
        and Path(a).parent.name == "hooks"
        for a in args
    )


def strip_ours(settings: dict) -> int:
    """Removes our hook entries, leaving everyone else's untouched.

    Returns how many were removed. Groups and events left empty are dropped so
    the file does not fill up with hollow structures.
    """
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return 0

    removed = 0
    for event in list(hooks):
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            if not isinstance(group, dict):
                kept_groups.append(group)
                continue
            entries = group.get("hooks")
            if not isinstance(entries, list):
                kept_groups.append(group)
                continue
            kept = [e for e in entries if not (isinstance(e, dict) and is_ours(e))]
            removed += len(entries) - len(kept)
            if kept:
                group["hooks"] = kept
                kept_groups.append(group)
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]

    if not hooks:
        settings.pop("hooks", None)
    return removed


def our_group(event: str, python: str, script: Path) -> dict:
    """The hook group this project adds for one event."""
    entry = {
        "type": "command",
        "command": python,
        "args": [str(script)],
        "async": True,
    }
    group: dict = {"hooks": [entry]}
    if event in TAKES_MATCHER:
        return {"matcher": "*", **group}
    return group


def add_ours(settings: dict, python: str) -> None:
    """Adds our hooks, keeping any other hooks already registered."""
    hooks = settings.setdefault("hooks", {})
    for script, events in ((NOTIFY, EVENTS), (LAUNCH, LAUNCH_EVENTS)):
        for event in events:
            groups = hooks.setdefault(event, [])
            if not isinstance(groups, list):
                raise SystemExit(
                    f"the {event!r} entry in {SETTINGS} is not a list. "
                    "Nothing changed."
                )
            groups.append(our_group(event, python, script))


def backup() -> Path | None:
    """Copies the settings file next to itself before touching it."""
    if not SETTINGS.is_file():
        return None
    spare = SETTINGS.with_suffix(".json.claude-cute-backup")
    shutil.copy2(SETTINGS, spare)
    return spare


def write_settings(settings: dict) -> None:
    """Writes atomically, so an interrupted run cannot truncate the file."""
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=SETTINGS.parent,
        prefix=SETTINGS.name,
        suffix=".tmp",
        delete=False,
    ) as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")
        temporary = Path(f.name)
    os.replace(temporary, SETTINGS)


def main() -> int:
    for script in (NOTIFY, LAUNCH):
        if not script.is_file():
            print(f"cannot find {script}. Run this from the project folder.")
            return 1

    settings = read_settings()
    spare = backup()
    replaced = strip_ours(settings)
    add_ours(settings, sys.executable)
    write_settings(settings)

    total = len(EVENTS) + len(LAUNCH_EVENTS)
    print(f"Claude Cute: registered {total} hooks in {SETTINGS}")
    if replaced:
        print(f"  replaced {replaced} entries from a previous install")
    if spare:
        print(f"  backup of the previous file: {spare}")
    print(f"  interpreter: {sys.executable}")
    print(f"  reports events: {NOTIFY}")
    print(f"  starts the widget: {LAUNCH}")
    print()
    print("Open a new session for it to take effect. To undo: py uninstall.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
