"""The state table: which ones exist, what inherits from what, what expires them.

Pure data and pure functions; the live machine is in `state_manager.py`.

States form a tree using `-` as the separator, so `working-bash` is a child of
`working`, which falls back to `idle` as the root. A state with no sprites of
its own borrows its nearest ancestor's, which is what lets a character be drawn
a few states at a time.

**To add a state**, everything happens in this file: the constant, its entry in
`STATES`, its line in `DESCRIPTIONS`, and — if needed — a parent in `PARENTS`,
the event that triggers it in `EVENTS`, or the tool that picks it in `FAMILIES`.
Sprites are optional. `tests/test_states.py` reports anything left half done.
"""

from __future__ import annotations

# --- States ------------------------------------------------------------------

IDLE = "idle"
IDLE_SLEEP = "idle-sleep"
THINKING = "thinking"
WORKING = "working"
WORKING_BASH = "working-bash"
WORKING_EDIT = "working-edit"
WORKING_READ = "working-read"
WORKING_WEB = "working-web"
WORKING_AGENT = "working-agent"
WAITING = "waiting"
DONE = "done"
ERROR = "error"
ERROR_API = "error-api"
WAKE = "wake"
SLEEP = "sleep"
COMPACTING = "compacting"
# The only state the session does not produce: the window imposes it while you
# drag the avatar, and the `StateManager` never hears about it.
DRAGGED = "dragged"

STATES = (
    IDLE,
    IDLE_SLEEP,
    THINKING,
    WORKING,
    WORKING_BASH,
    WORKING_EDIT,
    WORKING_READ,
    WORKING_WEB,
    WORKING_AGENT,
    WAITING,
    DONE,
    ERROR,
    ERROR_API,
    WAKE,
    SLEEP,
    COMPACTING,
    DRAGGED,
)

# The states Claude Code can produce: everything except `dragged`. Derived, so
# it cannot drift from `STATES`.
SESSION_STATES = tuple(s for s in STATES if s != DRAGGED)

SEPARATOR = "-"

# Explicit parents for states whose hierarchy the name does not imply. Whose
# sprites to borrow until a state has its own; purely about pixels.
PARENTS: dict[str, str] = {
    WAITING: THINKING,
    COMPACTING: THINKING,
    DRAGGED: WAITING,
    SLEEP: IDLE_SLEEP,
}

# --- How each state is explained to a person ---------------------------------

# One plain-language line per state, for anything that wants to say out loud
# what the dragon is doing. Every state needs an entry.
DESCRIPTIONS: dict[str, str] = {
    IDLE: "resting",
    IDLE_SLEEP: "asleep",
    THINKING: "thinking",
    WORKING: "using a tool",
    WORKING_BASH: "running a command",
    WORKING_EDIT: "writing files",
    WORKING_READ: "reading the code",
    WORKING_WEB: "searching the web",
    WORKING_AGENT: "delegating to subagents",
    WAITING: "waiting for you",
    DONE: "done",
    ERROR: "something failed",
    ERROR_API: "API error",
    WAKE: "waking up",
    SLEEP: "falling asleep",
    COMPACTING: "tidying up the context",
    DRAGGED: "being carried around",
}

# --- Automatic transitions ---------------------------------------------------

# States that expire into another one on their own: `{state: (seconds, next)}`.
#
# The rule for the seconds is **the animation plus about 600 ms of held pose**.
# Drawing slower animations for a new character means raising these, or the
# animation gets cut off; `main.py` warns at startup about both a state that
# gets cut and one that freezes too long on its last frame.
TRANSIENTS: dict[str, tuple[float, str]] = {
    DONE: (1.3, IDLE),
    WAKE: (1.2, IDLE),
    ERROR: (1.2, IDLE),
    ERROR_API: (1.2, IDLE),
    SLEEP: (1.4, IDLE_SLEEP),
}

# Transient states play once and hold their last frame. Derived, not a second
# list to keep in sync.
ONE_SHOT = frozenset(TRANSIENTS)

# Seconds of resting before the dragon falls asleep.
SLEEP_AFTER = 300.0

# Safety net: seconds an active state may go without news before giving up and
# returning to `idle`. Short on purpose — showing something no longer true is
# worse than giving up early. Every active state gets one.
STALL_AFTER: dict[str, float] = {
    WORKING: 120.0,  # inherited by working-bash, working-edit, etc.
    # Not stalled but waiting for a person, so it is given the whole workday.
    WAITING: 8 * 3600.0,
}
STALL_DEFAULT = 45.0


def stall_limit(state: str) -> float:
    """Seconds `state` may go without news before giving up."""
    for candidate in kinds(state):
        if candidate in STALL_AFTER:
            return STALL_AFTER[candidate]
    return STALL_DEFAULT


# --- Translating events ------------------------------------------------------

EVENTS: dict[str, str] = {
    "SessionStart": WAKE,
    "UserPromptSubmit": THINKING,
    "PreToolUse": WORKING,  # refined with tool_name
    "PostToolUse": THINKING,
    "PostToolUseFailure": ERROR,
    "PermissionRequest": WAITING,
    "Notification": WAITING,
    "SubagentStart": WORKING_AGENT,
    # Anything *finishing* goes back to reading the result, not to working.
    "SubagentStop": THINKING,
    "TaskCreated": WORKING_AGENT,
    "TaskCompleted": THINKING,
    "PermissionDenied": THINKING,
    "PostToolBatch": THINKING,
    "PreCompact": COMPACTING,
    # When compaction ends the only certain thing is that it ended.
    "PostCompact": IDLE,
    "Stop": DONE,
    "StopFailure": ERROR_API,
    "SessionEnd": SLEEP,
}

# Events that only make sense inside a turn. Arriving after the `Stop` they
# are stragglers and must not revive the working animation.
TURN_SCOPED = frozenset({
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PostToolBatch",
    "SubagentStart",
    "SubagentStop",
    "TaskCreated",
    "TaskCompleted",
})

# Events that open a turn (or claim it from another session).
START_TURN = frozenset({"UserPromptSubmit", "SessionStart"})

# Seconds a session with no events is still considered alive. Generous, since
# a session can stay quiet while the user reads code.
SESSION_ALIVE = 1800.0

# Seconds the widget stays on with every session gone before closing itself.
# The grace covers `SessionEnd`/`SessionStart` pairs seconds apart, which an
# editor restart produces.
CLOSE_AFTER = 300.0

# Seconds into the future a hook's timestamp may be before it is treated as a
# broken clock rather than as an ordering claim. Guards against a clock that
# moved: NTP stepping, a VM resuming, a dual-boot keeping local time.
CLOCK_SKEW = 60.0

# Seconds stragglers are ignored after a `Stop`.
TURN_END_GRACE = 15.0

# Which state each tool gets. Claude Code sends the raw tool name and groups
# nothing, so this grouping is the project's own. A tool that is not listed
# falls back to generic `working`, which is how new tools stay harmless.
FAMILIES: dict[str, str] = {
    "Bash": WORKING_BASH,
    "BashOutput": WORKING_BASH,
    "KillShell": WORKING_BASH,
    "PowerShell": WORKING_BASH,  # a terminal, same as Bash
    "Edit": WORKING_EDIT,
    "Write": WORKING_EDIT,
    "MultiEdit": WORKING_EDIT,
    "NotebookEdit": WORKING_EDIT,
    "Read": WORKING_READ,
    "Glob": WORKING_READ,
    "Grep": WORKING_READ,
    "LS": WORKING_READ,
    "NotebookRead": WORKING_READ,
    "WebSearch": WORKING_WEB,
    "WebFetch": WORKING_WEB,
    "Task": WORKING_AGENT,
    "Agent": WORKING_AGENT,
    # The exception to everything here being work: asking you something is
    # waiting for you.
    "AskUserQuestion": WAITING,
}


def ancestors(state: str) -> list[str]:
    """The chain of states to try, most specific first.

    `working-bash` -> `["working-bash", "working", "idle"]`

    The animation engine walks it until it finds a folder with frames.
    """
    chain: list[str] = []
    current: str | None = state
    while current and current not in chain:
        chain.append(current)
        if current in PARENTS:
            current = PARENTS[current]
        elif SEPARATOR in current:
            current = current.rsplit(SEPARATOR, 1)[0]
        else:
            current = None
    if IDLE not in chain:
        chain.append(IDLE)
    return chain


def kinds(state: str) -> list[str]:
    """The chain of what a state **is**, most specific first.

    `working-bash` -> `["working-bash", "working"]`

    Follows the name only. `PARENTS` is deliberately left out: it says whose
    sprites to borrow, which is a question about pixels, not about meaning.
    """
    chain: list[str] = []
    current: str | None = state
    while current and current not in chain:
        chain.append(current)
        current = (
            current.rsplit(SEPARATOR, 1)[0] if SEPARATOR in current else None
        )
    return chain


def state_for(event: str, tool_name: str | None = None) -> str:
    """Translates a hook event (and its tool) into a state."""
    base = EVENTS.get(event, IDLE)
    if base == WORKING and tool_name:
        return FAMILIES.get(tool_name, WORKING)
    return base
