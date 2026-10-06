"""Watches the Claude Code processes behind the sessions.

A session can end without a `SessionEnd`: the terminal closed outright, the
desktop app quit, Claude Code killed. Its process going away is the one signal
that never gets lost, so the hook sends its pid and this answers whether it is
still there.

Three answers, not two. "Unknown" (the system refused to say) leaves the
session to the silence net, exactly as if no pid had been sent.

Plain Python, no Qt, like the `StateManager` that uses it.
"""

from __future__ import annotations

import os
import sys

# What `OpenProcess` needs to wait on a process and nothing more.
_SYNCHRONIZE = 0x00100000
_QUERY_LIMITED = 0x1000
_WAIT_TIMEOUT = 0x102
_ERROR_INVALID_PARAMETER = 87  # no such process


class ProcessWatch:
    """Answers whether a pid is alive, without being fooled by pid reuse.

    On Windows a handle is opened the first time a pid is seen and kept until
    `forget()`. While it is open Windows cannot hand that number to another
    program, so a recycled pid can never pass for the original. On Unix there
    is no such thing; a signal 0 is the usual check and reuse within a session
    is not a realistic worry.
    """

    def __init__(self) -> None:
        self._handles: dict[int, int] = {}

    def alive(self, pid: int) -> bool | None:
        """True if running, False if gone, None if the system will not say."""
        try:
            if sys.platform == "win32":
                return self._alive_windows(pid)
            return self._alive_unix(pid)
        except Exception:  # noqa: BLE001 — unknown, never a crash
            return None

    def forget(self, pid: int) -> None:
        """Lets go of a pid whose session is over."""
        handle = self._handles.pop(pid, None)
        if handle is not None:
            _kernel32().CloseHandle(handle)

    def forget_all(self) -> None:
        for pid in list(self._handles):
            self.forget(pid)

    def _alive_windows(self, pid: int) -> bool | None:
        import ctypes

        kernel32 = _kernel32()
        handle = self._handles.get(pid)
        if handle is None:
            handle = kernel32.OpenProcess(_SYNCHRONIZE | _QUERY_LIMITED, False, pid)
            if not handle:
                if ctypes.get_last_error() == _ERROR_INVALID_PARAMETER:
                    return False
                return None  # access denied and the like
            self._handles[pid] = handle
        return kernel32.WaitForSingleObject(handle, 0) == _WAIT_TIMEOUT

    @staticmethod
    def _alive_unix(pid: int) -> bool | None:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # it exists; it just is not ours to signal
        return True


_KERNEL32 = None


def _kernel32():
    global _KERNEL32
    if _KERNEL32 is None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        _KERNEL32 = kernel32
    return _KERNEL32
