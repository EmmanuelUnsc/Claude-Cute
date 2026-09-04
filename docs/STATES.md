# The states: what triggers them and how to reproduce them

Sixteen of them come from Claude Code. One, `dragged`, comes from you.

A complete reference. For each state: which Claude Code event activates it,
what it takes to trigger it deliberately, how long it lasts and what happens
next.

All of this comes from `src/states.py`. If anything here disagrees with the
code, the code wins.

> **An event that is not registered in `settings.json` never fires.** Mapping it
> in `EVENTS` is only half the job; the other half is Claude Code knowing it
> has to report it. See the README for the full list.

## Forcing any state without waiting

Three ways, from most direct to most realistic:

```bash
# 1. The avatar's menu: right click -> "Force state". Instant.

# 2. Push the state over HTTP, bypassing the event logic:
curl -X POST http://127.0.0.1:8770/event -H "Content-Type: application/json" -d "{\"state\":\"waiting\"}"

# 3. Simulate the real event, with all the logic in between:
python hooks/notify.py PreCompact
python hooks/notify.py PreToolUse Bash
```

The third one is what to use for real testing: it goes through `EVENTS`,
`FAMILIES` and all of the `StateManager`'s filters, exactly as in production.

---

## The table

| State | Triggered by | How to really cause it | Lasts | Then |
|---|---|---|---|---|
| `idle` | Nothing / expiry / `PostCompact` | Stop working | until the next event | `idle-sleep` after 300 s |
| `idle-sleep` | 300 s in `idle` | Wait five minutes | until the next event | — |
| `thinking` | `UserPromptSubmit`, `PostToolUse`, `SubagentStop`, `TaskCompleted`, `PermissionDenied`, `PostToolBatch` | Send a prompt | until the next event | safety net after 45 s |
| `working` | `PreToolUse` with an **unclassified** tool | Use an MCP tool, `Skill`, `ToolSearch`… | while it runs | safety net after 120 s |
| `working-bash` | `PreToolUse` with `Bash`, `BashOutput`, `KillShell`, `PowerShell` | Ask for a terminal command | while it runs | 120 s |
| `working-edit` | `PreToolUse` with `Edit`, `Write`, `MultiEdit`, `NotebookEdit` | Ask it to modify a file | while it runs | 120 s |
| `working-read` | `PreToolUse` with `Read`, `Glob`, `Grep`, `LS`, `NotebookRead` | Ask it to read or search the code | while it runs | 120 s |
| `working-web` | `PreToolUse` with `WebSearch`, `WebFetch` | Ask it to look something up online | while it runs | 120 s |
| `working-agent` | `SubagentStart`, `TaskCreated`, or `PreToolUse` with `Task`/`Agent` | Ask it to delegate to a subagent | while it runs | 120 s |
| `waiting` | `PermissionRequest`, `Notification`, or `PreToolUse` with `AskUserQuestion` | Ask for something that needs your approval | until you answer | safety net after **8 h** |
| `done` | `Stop` | Let Claude finish its turn | 1.3 s | `idle` |
| `error` | `PostToolUseFailure` | Ask for a command that fails (`exit 1`) | 1.2 s | `idle` |
| `error-api` | `StopFailure` | Cannot be triggered on purpose | 1.2 s | `idle` |
| `wake` | `SessionStart` | Open a Claude Code session | 1.2 s | `idle` |
| `sleep` | `SessionEnd` | Close a Claude Code session | 1.4 s | `idle-sleep` |
| `compacting` | `PreCompact` | Run `/compact` by hand | until `PostCompact` | safety net after 45 s |
| `dragged` | **no event** | Drag the avatar with the left button | while you hold it | never — it is not the session's |

---

## The tools that are classified

This comes from `FAMILIES` in `states.py`. Any tool not listed here falls back
to generic `working`.

| Family | Tools |
|---|---|
| `working-bash` | `Bash`, `BashOutput`, `KillShell`, `PowerShell` |
| `working-edit` | `Edit`, `Write`, `MultiEdit`, `NotebookEdit` |
| `working-read` | `Read`, `Glob`, `Grep`, `LS`, `NotebookRead` |
| `working-web` | `WebSearch`, `WebFetch` |
| `working-agent` | `Task`, `Agent` |
| **`waiting`** | **`AskUserQuestion`** |

**`AskUserQuestion` is the exception to everything here being work.** When
Claude asks you a question it is not working, it is waiting for you. There used
to be a rule requiring every family to be a child of `working`; it was relaxed
deliberately, and a test documents why.

**How this table was built: by measuring.** Before adding `PowerShell`, 12% of
tool uses fell into generic `working` — 73 uses of a terminal that was not
breathing fire. The ones still unclassified (`Skill`, `ToolSearch`, MCP tools)
are left that way on purpose: low volume and no natural family. That is what
the fallback is for.

---

## The four clocks that govern everything

Do not confuse them: they do different things and live in different files.

| Clock | Where | What it controls |
|---|---|---|
| `ms_per_frame` | `assets/<character>/character.json` | How fast each animation is drawn |
| `TRANSIENTS` | `src/states.py` | How long a state lasts before expiring on its own |
| `MIN_CYCLES` | `src/smoothing.py` | How much screen time an animation is reserved |
| `STALL_AFTER` | `src/states.py` | How much silence is tolerated before going back to `idle` |

### Animation vs expiry, calibrated

One-shot states freeze on their last frame until they expire. The rule is
**animation plus 600 ms of held pose**: a held instant reads as intent, two
seconds reads as a hang.

| State | Animation | Expires at | Frozen |
|---|---|---|---|
| `done` | 640 ms | 1300 ms | 660 ms |
| `error` | 550 ms | 1200 ms | 650 ms |
| `sleep` | 800 ms | 1400 ms | 600 ms |
| `wake` | 600 ms | 1200 ms | 600 ms |

Before calibration those freezes ran from 900 to 2360 ms — up to 79% of the
time on screen was a still frame.

`main.py` warns at startup about both problems: the animation that does not fit
and gets cut (`truncated_states`), and the one with so much time left over that
the pose is held too long (`frozen_states`). **If you draw a character with
different speeds, watch those warnings**: the timings above are calibrated for
this project's default character.
