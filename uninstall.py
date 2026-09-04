"""Undoes `install.py`: removes the hand-registered hooks.

Only the entries this project added are removed. Anything else in
`~/.claude/settings.json` — including hooks from other tools — is left exactly
as it was, and a backup is written before anything changes.

    py uninstall.py

This does not touch the plugin. To remove that, use Claude Code's own
`/plugin` command.
"""

from __future__ import annotations

from install import SETTINGS, backup, read_settings, strip_ours, write_settings


def main() -> int:
    if not SETTINGS.is_file():
        print(f"there is no {SETTINGS}: nothing to undo")
        return 0

    settings = read_settings()
    spare = backup()
    removed = strip_ours(settings)

    if not removed:
        print(f"no Claude Cute hooks found in {SETTINGS}: nothing changed")
        if spare:
            spare.unlink(missing_ok=True)
        return 0

    write_settings(settings)
    print(f"Claude Cute: removed {removed} hooks from {SETTINGS}")
    if spare:
        print(f"  backup of the previous file: {spare}")
    print()
    print("The library it may have downloaded lives in ~/.claude/claude-cute/;")
    print("delete that folder too if you are done with the widget.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
