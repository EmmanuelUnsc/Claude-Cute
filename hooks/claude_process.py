"""Finds the Claude Code process that started this hook.

The widget watches that process so it can tell a session is over even when no
`SessionEnd` arrives: a terminal closed outright, the desktop app quit, Claude
Code killed. Each desktop-app session is a Claude Code process of its own, so
this works the same there as in a terminal.

Measured on Windows from the desktop app:

    python.exe -> py.exe -> bash.exe x3 -> claude.exe (the session)
                                        -> claude.exe (the desktop app)

The nearest `claude` is the session. Everything below it is plumbing — the
shell the hook runs under, the Python launcher — and is skipped. Anything else
before a `claude` means this was not started by Claude Code (someone ran the
hook by hand), and the answer is None: no PID beats a wrong one, since a PID
that never dies would keep a session alive forever.

Like everything the hook runs, it never raises.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Callable

# What Claude Code runs as: the native build, or the npm package on a runtime.
CLAUDE_NAMES = ("claude",)
RUNTIMES = frozenset({"node", "bun"})

# What may sit between Claude Code and this script.
PLUMBING = frozenset({
    "bash", "sh", "dash", "zsh", "fish", "env",
    "cmd", "powershell", "pwsh", "conhost",
    "py", "pyw",
})

# Far more than the six levels measured; only a guard against a cycle.
MAX_DEPTH = 16

# (parent pid, process name) for a pid, or None if it does not exist.
Lookup = Callable[[int], "tuple[int, str] | None"]


def _bare(name: str) -> str:
    """`C:\\...\\Python313.EXE` -> `python313`."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _is_claude(name: str) -> bool:
    return name.startswith(CLAUDE_NAMES) or name in RUNTIMES


def _is_plumbing(name: str) -> bool:
    # Python goes by many names: python3, python3.13, pythonw, python313.
    return name in PLUMBING or name.startswith("python")


def find(start: int, lookup: Lookup) -> int | None:
    """Walks up from `start` to the nearest Claude Code process."""
    seen = set()
    pid = start
    for _ in range(MAX_DEPTH):
        if pid in seen:
            return None
        seen.add(pid)
        entry = lookup(pid)
        if entry is None:
            return None
        parent, name = entry
        name = _bare(name)
        if pid != start:
            if _is_claude(name):
                return pid
            if not _is_plumbing(name):
                return None
        if parent <= 0 or parent == pid:
            return None
        pid = parent
    return None


# --- what each system offers ---------------------------------------------------


def _windows_table() -> dict[int, tuple[int, str]]:
    """Every process at once: one snapshot is cheaper than asking per pid."""
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if snapshot in (None, wintypes.HANDLE(-1).value):
        return {}
    table = {}
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(Entry)
        found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            table[entry.th32ProcessID] = (
                entry.th32ParentProcessID, entry.szExeFile
            )
            found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return table


def _proc(pid: int) -> tuple[int, str] | None:
    """Linux: `/proc/<pid>/stat`, read without spawning anything."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            stat = f.read()
    except OSError:
        return None
    # The name sits in parentheses and may itself contain spaces or `)`.
    name = stat[stat.index("(") + 1 : stat.rindex(")")]
    parent = int(stat[stat.rindex(")") + 2 :].split()[1])
    return parent, name


def _ps(pid: int) -> tuple[int, str] | None:
    """macOS and other Unixes: no `/proc`, so ask `ps`."""
    try:
        out = subprocess.run(
            ["ps", "-o", "ppid=,comm=", "-p", str(pid)],
            capture_output=True, text=True, timeout=1,
        ).stdout.strip()
        parent, name = out.split(None, 1)
        return int(parent), name
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def claude_pid() -> int | None:
    """The pid of the Claude Code process above this one, if there is one."""
    try:
        if sys.platform == "win32":
            lookup: Lookup = _windows_table().get
        elif os.path.isdir("/proc"):
            lookup = _proc
        else:
            lookup = _ps
        return find(os.getpid(), lookup)
    except Exception:  # noqa: BLE001 — the hook must never fail
        return None
