#!/usr/bin/env bash
# Finds a Python 3.10+ on this machine and runs the hook with it.
#
# The plugin used to ask for this at install time, as a `userConfig` option.
# That was wrong twice over: pressing Esc on the question installed the plugin
# with no answer at all — Claude Code then refuses to run every one of the
# eighteen hooks, two error lines per tool call — and even a user who answered
# had to know whether their Python came from python.org (`py`) or the
# Microsoft Store (`python`). Nobody installing a desktop pet should have to
# know that. So the question is gone and this file answers it instead.
#
# Called from `hooks.json` as:
#   bash "${CLAUDE_PLUGIN_ROOT}/hooks/cute-python.sh" \
#        "${CLAUDE_PLUGIN_ROOT}/hooks/notify.py"
# Everything after this script's own path is handed to the interpreter.
#
# The three Windows defences below are not hypothetical: they are the ones
# Anthropic's own `security-guidance` plugin hit and documented in
# `sg-python.sh`, which this file follows.

# --- Silence -----------------------------------------------------------------
# The rest of the project promises that a machine without Python simply gets no
# dragon, never an error in your way. Eighteen hooks firing on every tool call
# make that promise load-bearing: one line on stderr here is two lines of noise
# per tool call, forever. So every failure path below exits 0, and the reason is
# written where `/claude-cute:doctor` can read it back on request.
STATE="${HOME}/.claude/claude-cute"
COMPLAINT="${STATE}/.no-python"

give_up() {
    mkdir -p "$STATE" 2>/dev/null && cat > "$COMPLAINT" 2>/dev/null <<EOF
$(date)
No Python 3.10 or newer was found on this machine.

Tried, in order: python3.13, python3.12, python3.11, python3.10,
python3, python, py -3

On Windows, install Python from https://python.org — not from the Microsoft
Store, whose \`python3\` is a stub that exits 49 without running anything.
On macOS: brew install python. On Linux, use your package manager.

Delete this file once Python is installed; it is only a note to the doctor.
EOF
    exit 0
}

# Force UTF-8 for every Python filesystem and IO operation (PEP 540).
# Without it, Python on Windows takes `locale.getpreferredencoding()` from the
# system codepage — cp1252 on a Spanish install — and any path holding a byte
# undefined there raises inside `open()` or `json.load`. The widget reads
# `config.json` and the hook payload on stdin, so this is on its critical path.
# It has to be set before Python starts; changing it from inside is too late.
export PYTHONUTF8=1

# Git Bash hands us POSIX paths (`/c/Users/...`). We usually end up executing a
# native `python.exe`, which reads a leading `/` as the root of the current
# drive: `/c/Users/x/notify.py` becomes `C:\c\Users\x\notify.py`, does not
# exist, and the hook dies. `cygpath` is a Git Bash builtin and absent
# everywhere else, so the guard makes this a no-op on macOS and Linux. It is
# idempotent on paths that are already in Windows form.
if command -v cygpath >/dev/null 2>&1; then
    converted=()
    for a in "$@"; do
        case "$a" in
            /*) converted+=("$(cygpath -w "$a")") ;;
            *)  converted+=("$a") ;;
        esac
    done
    set -- "${converted[@]}"
fi

# Asks an interpreter for its version. Printing rather than trusting the exit
# code is what unmasks the Microsoft Store stub: it sits on the PATH as
# `python3.exe`, runs nothing, and exits 49. Anything that cannot answer this
# question is not a Python we can use.
probe() {
    "$@" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null
}

# PySide6 6.7 and the widget's own syntax need 3.10. Below that the import
# fails and the user gets a silent no-op, so it is better to keep looking.
new_enough() {
    case "$1" in
        3.1[0-9]|3.[2-9][0-9]|[4-9].*|[1-9][0-9].*) return 0 ;;
        *) return 1 ;;
    esac
}

# Pass 1 — version-suffixed binaries, newest first. These exist only where
# somebody installed them deliberately (python.org, Homebrew, pyenv), so
# choosing one here beats whatever the bare name happens to point at, without
# asking the user to reorder their PATH.
for cmd in python3.13 python3.12 python3.11 python3.10; do
    version=$(probe "$cmd") || continue
    new_enough "$version" && exec "$cmd" "$@"
done

# Pass 2 — the bare names. `python3` is right on macOS and Linux and is the
# Store stub on Windows, where `python` and `py -3` are the real ones; probing
# in this order lets the same list serve every platform. Unquoted on purpose:
# `py -3` has to split into a command and an argument.
for cmd in "python3" "python" "py -3"; do
    # shellcheck disable=SC2086
    version=$(probe $cmd) || continue
    # shellcheck disable=SC2086
    new_enough "$version" && exec $cmd "$@"
done

give_up
