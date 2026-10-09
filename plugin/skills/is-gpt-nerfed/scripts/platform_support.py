"""Small standard-library helpers for the shared backend's OS-specific operations."""
from __future__ import annotations

import contextlib
import os
import subprocess
import sys


@contextlib.contextmanager
def exclusive_file_lock(fileobj):
    """Hold an exclusive cross-process lock on the first byte of an open file.

    LockFileEx waits until the range is available; unlike msvcrt.LK_LOCK it has no
    built-in ten-retry timeout. On POSIX, flock provides the same lifetime semantics.
    """
    if sys.platform == "win32":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        class OVERLAPPED(ctypes.Structure):
            _fields_ = [
                ("Internal", ctypes.c_size_t),
                ("InternalHigh", ctypes.c_size_t),
                ("Offset", wintypes.DWORD),
                ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE),
            ]

        fileobj.seek(0, os.SEEK_END)
        if fileobj.tell() == 0:
            fileobj.write("\0")
            fileobj.flush()
        handle = wintypes.HANDLE(msvcrt.get_osfhandle(fileobj.fileno()))
        overlapped = OVERLAPPED()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        lock_file = kernel32.LockFileEx
        lock_file.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                              wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(OVERLAPPED))
        lock_file.restype = wintypes.BOOL
        unlock_file = kernel32.UnlockFileEx
        unlock_file.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                wintypes.DWORD, ctypes.POINTER(OVERLAPPED))
        unlock_file.restype = wintypes.BOOL
        if not lock_file(handle, 0x00000002, 0, 1, 0, ctypes.byref(overlapped)):
            error = ctypes.get_last_error()
            raise OSError(error, ctypes.FormatError(error))
        try:
            yield
        finally:
            if not unlock_file(handle, 0, 1, 0, ctypes.byref(overlapped)):
                error = ctypes.get_last_error()
                raise OSError(error, ctypes.FormatError(error))
        return

    import fcntl

    fcntl.flock(fileobj, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(fileobj, fcntl.LOCK_UN)


def pid_alive(pid) -> bool:
    """Check a PID without sending it a signal (important on Windows)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        open_process.restype = wintypes.HANDLE
        handle = open_process(0x00100000, False, pid)  # SYNCHRONIZE only; no terminate rights
        if not handle:
            # Access denied means the process may exist but its handle is protected.
            return ctypes.get_last_error() == 5
        try:
            wait = kernel32.WaitForSingleObject
            wait.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            wait.restype = wintypes.DWORD
            result = wait(handle, 0)
            return result == 0x00000102  # WAIT_TIMEOUT: process is still running
        finally:
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = (wintypes.HANDLE,)
            close_handle.restype = wintypes.BOOL
            close_handle(handle)

    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def subprocess_options(hidden: bool = False, detached: bool = False) -> dict:
    """Return flags for detached/hidden background children without opening a Windows console."""
    if sys.platform == "win32":
        return {"creationflags": 0x08000000} if hidden else {}
    return {"start_new_session": True} if detached else {}


def command_argv(executable: str, arguments=()) -> list[str] | str:
    """Build a launchable argv for native executables, Python fakes, and npm .cmd shims."""
    executable = os.fspath(executable)
    arguments = [str(arg) for arg in arguments]
    suffix = os.path.splitext(executable)[1].lower()
    if suffix == ".py":
        return [sys.executable, "-X", "utf8", executable, *arguments]
    if sys.platform == "win32" and suffix == ".cmd":
        comspec = os.environ.get("COMSPEC") or os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe")
        prefix = subprocess.list2cmdline([comspec, "/d", "/s", "/c"])
        def quote_batch_arg(value: str) -> str:
            if any(char in value for char in ('"', "%", "!", "\r", "\n")):
                raise ValueError("cannot safely forward quotes, %, !, or newlines to a Windows .cmd Codex shim")
            trailing_slashes = len(value) - len(value.rstrip("\\"))
            body = value[:-trailing_slashes] if trailing_slashes else value
            return '"' + body + ("\\" * (2 * trailing_slashes)) + '"'

        command = " ".join(quote_batch_arg(value) for value in [executable, *arguments])
        # Keep this a command-line string: passing a list makes Python escape the
        # nested quotes that cmd /s /c needs to preserve an executable path with spaces.
        return prefix + ' "' + command + '"'
    return [executable, *arguments]


def app_codex_bins(mac_bins=()) -> list[str]:
    """Return desktop-bundled Codex CLI paths for the current platform."""
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            return []
        import glob

        return sorted(glob.glob(os.path.join(local, "OpenAI", "Codex", "bin", "*", "codex.exe")))
    if sys.platform == "darwin":
        return list(mac_bins)
    return []


def is_desktop_codex(executable: str | None) -> bool:
    if not executable:
        return False
    path = os.path.normcase(os.path.normpath(executable))
    if sys.platform == "win32":
        return os.path.normcase(os.path.join("OpenAI", "Codex", "bin")) in path
    return ".app/Contents/" in executable
