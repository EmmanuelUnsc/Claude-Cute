---
description: Works out why the Claude Cute dragon is not on screen, and what to do about it
allowed-tools: ["Read", "Bash", "Glob"]
---

# Why the dragon is not there

Work through these in order and stop at the first thing that is actually wrong.
Report what you found in a few sentences, plainly, and say what the user should
do. Do not print a checklist of everything that passed — they asked because
something is broken, not for an inventory.

This command exists because the widget is deliberately silent. Every failure
path in the plugin swallows its error rather than interrupting a turn, since
eighteen hooks fire on every tool call and one line of noise each would be
unbearable. The reasons get written to files instead. **You are the thing that
reads those files.**

## 1. Has this session even loaded the hooks?

Hooks are read when a session starts. A conversation that was already open when
the plugin was installed never had them, and never will. If the plugin was
installed minutes ago in this same conversation, that alone is the answer:
open a new session. Nothing below matters yet.

## 2. Is there a Python the plugin can find?

Read `~/.claude/claude-cute/.no-python`. If that file exists, the shim
(`hooks/cute-python.sh`) searched and came up empty. The file says what it
tried; show the user its contents and stop here. The fix is installing Python
3.10+ — on Windows from python.org, **not** the Microsoft Store, whose
`python3` sits on the PATH, runs nothing, and exits 49.

If the file does not exist, confirm the shim works now:

```
bash "<plugin>/hooks/cute-python.sh" -c "import sys; print(sys.executable, sys.version)"
```

## 3. Is `bash` there at all?

On Windows, Claude Code uses Git Bash when Git for Windows is installed and
PowerShell when it is not. The hooks are written in shell form and start with
`bash`, so a machine without it runs nothing and says nothing — the one gap the
`.no-python` note cannot report, because the shim never got to run.

Check whether `bash` resolves. If it does not, that is the diagnosis, and the
fix is either installing Git for Windows or using the standalone route:
`py install.py` from a clone of the repository, which registers the same hooks
with a direct path to the user's Python and no shell involved.

## 4. Did the graphics library fail to install?

The plugin fetches PySide6 once, into `~/.claude/claude-cute/lib/`. Look in
`~/.claude/claude-cute/`:

- **`.install-failed`** — the install failed and a six-hour cooldown is
  running. **Read this file and show it.** It holds the tail of pip's error and
  is the only record of what went wrong; nothing else will ever surface it.
  Deleting it lifts the cooldown and the next session retries.
- **`.installing`** — an install is in flight. PySide6 is about 100 MB, so a
  few minutes is normal; tell the user to wait and reopen a session. A marker
  older than twenty minutes is stale and ignored by the code. A marker of zero
  bytes is debris from an interrupted install: it blocks for twenty minutes and
  can be deleted.
- **`lib/`** — the library landed. Verify the import the way the widget does,
  with `PYTHONPATH` pointing there. A bare `import PySide6` proves nothing:
  this install is private and never touches `site-packages`.

## 5. Is a widget already running, on which port?

Do not assume 8770. If that port is taken the widget moves up and records where
it landed in `config.json`, which lives in the plugin's own install directory —
find it via `installPath` in `~/.claude/plugins/installed_plugins.json`, since
the path carries the version number. **Read `config.json` and use the port it
says**, then ask the widget:

```
GET http://127.0.0.1:<port>/state
```

A JSON object with a `state` key means the widget is alive and receiving
events, and the problem is elsewhere — most likely it is running off-screen or
behind a window.

Ignore `.launching`. It is not an activity indicator: `launch.py` returns before
touching it whenever a widget is already up, so a stale marker means things are
fine, not broken.

## 6. If everything above is healthy

Say so, and mention the one thing that is easy to miss: **the desktop app does
not display hook errors.** The terminal prints them; the desktop app shows
nothing at all. So if the user is in the desktop app and something in the hook
chain is failing for a reason none of the files above captured, running the
same session once in a terminal is the fastest way to see the real message.
