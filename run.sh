#!/usr/bin/env bash
# Starts the widget on Linux. Two roles, and they are not the same job:
#
#   ./run.sh            someone running it from a clone of the repository.
#                       Checks out loud and says what is missing.
#   ./run.sh --quiet    invoked by a hook. Says nothing and asks nothing: a
#                       prompt here would leave Claude Code waiting forever for
#                       a keypress nobody is going to give it, and anything
#                       printed could surface as an error in the session.
#
# In both roles the failures are the same and so is the exit code; what changes
# is who is listening.
#
# **This file must keep LF line endings.** Written on Windows it comes out with
# CRLF, and then bash fails on the shebang itself with a "bad interpreter", or
# reports the stray carriage return as a command that does not exist. Neither
# message hints at the real cause.

quiet=0
[ "${1:-}" = "--quiet" ] && quiet=1

say() { [ "$quiet" -eq 1 ] || printf '%s
' "$*"; }
fail() {
    # Silent when a hook is listening: the exit code is the whole message.
    [ "$quiet" -eq 1 ] || printf 'ERROR: %s
' "$*" >&2
    exit 1
}

# Everything is relative to the project, not to wherever it was called from.
cd "$(dirname "$0")" || fail "cannot enter this script's folder"

[ -f main.py ] || fail "cannot find main.py. This script has to sit next to it (looked in $PWD)"

# `python3` first: on many distributions `python` is missing entirely, and on
# the older ones it is still Python 2. The version is checked here rather than
# left to blow up inside the program, where the error would be a syntax error
# in a file the user did not write.
PY=""
for candidate in python3 python; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
done
[ -n "$PY" ] || fail "no Python 3.10 or newer found. Install it from your distribution's packages."

# A warning and not a barrier, same as run.bat: a check with a false negative
# would leave you unable to start the program at all. If it fails, it says so
# and tries anyway.
if ! "$PY" -c 'import PySide6' >/dev/null 2>&1; then
    say "WARNING: could not import PySide6. Details:"
    say ""
    [ "$quiet" -eq 1 ] || "$PY" -c 'import PySide6'
    say ""
    say "If the avatar does not show up, install it with:"
    say "    $PY -m pip install -r requirements.txt"
    say ""
fi

# Detached on purpose: the widget has to outlive whoever started it. A hook is
# a short-lived process and a terminal gets closed; neither should take the
# dragon down with it.
nohup "$PY" main.py >/dev/null 2>&1 &

say "Claude Cute started (PID $!)."
say "Its diagnostic output is discarded here. To read it, run it in the"
say "foreground instead:  $PY main.py"
exit 0
