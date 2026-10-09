"""Small Shell_NotifyIcon wrapper for the Windows panel (no third-party package)."""
from __future__ import annotations

import ctypes
import os
import queue
import threading
from ctypes import wintypes
from typing import Callable


class TrayUnavailable(RuntimeError):
    pass


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


class TrayIcon:
    """Own an invisible Win32 window on a message thread and publish tray actions."""

    WM_APP = 0x8000
    WM_TRAY = WM_APP + 1
    WM_DISPATCH = WM_APP + 2
    WM_NULL = 0x0000
    WM_CLOSE = 0x0010
    WM_DESTROY = 0x0002
    WM_COMMAND = 0x0111
    WM_LBUTTONUP = 0x0202
    WM_LBUTTONDBLCLK = 0x0203
    WM_RBUTTONUP = 0x0205
    WM_CONTEXTMENU = 0x007B

    NIM_ADD = 0x00000000
    NIM_MODIFY = 0x00000001
    NIM_DELETE = 0x00000002
    NIF_MESSAGE = 0x00000001
    NIF_ICON = 0x00000002
    NIF_TIP = 0x00000004
    NIF_INFO = 0x00000010
    NIIF_INFO = 0x00000001
    IDI_APPLICATION = 32512
    MF_STRING = 0x00000000
    MF_SEPARATOR = 0x00000800
    TPM_RIGHTBUTTON = 0x0002
    TPM_RETURNCMD = 0x0100
    TPM_BOTTOMALIGN = 0x0020
    ID_SHOW = 1001
    ID_QUIT = 1002

    def __init__(self, on_action: Callable[[str], None]):
        self.on_action = on_action
        self.ready = False
        self.failed = False
        self.error: str | None = None
        self._thread: threading.Thread | None = None
        self._hwnd = None
        self._lock = threading.Lock()
        self._commands: queue.Queue[tuple] = queue.Queue()
        self._stop_requested = False
        self._added = False
        self._class_registered = False
        self._instance = None
        self._status = "Starting"
        self._class_name = f"IfGptNerfedTrayWindow_{id(self):x}"
        self._user32 = None
        self._shell32 = None
        self._kernel32 = None
        self._wndproc_callback = None

    @property
    def available(self) -> bool:
        return self.ready

    def start(self) -> None:
        if os.name != "nt":
            self.failed = True
            self.error = "The Windows notification area is available only on Windows."
            return
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._message_loop, name="nerfed-tray", daemon=True)
        self._thread.start()

    def set_status(self, status: str) -> None:
        self._status = str(status or "Status unknown")
        self._dispatch(("status", self._status))

    def notify(self, title: str, message: str) -> None:
        self._dispatch(("notify", str(title), str(message)))

    def _dispatch(self, command: tuple) -> None:
        with self._lock:
            hwnd = self._hwnd
            if self._stop_requested:
                return
        self._commands.put(command)
        if hwnd:
            self._user32.PostMessageW(hwnd, self.WM_DISPATCH, 0, 0)

    def stop(self) -> None:
        with self._lock:
            if self._stop_requested:
                return
            self._stop_requested = True
            hwnd = self._hwnd
        if hwnd:
            self._user32.PostMessageW(hwnd, self.WM_CLOSE, 0, 0)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.5)

    def _load_api(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        self._kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self._kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        self._user32.RegisterClassW.argtypes = [ctypes.c_void_p]
        self._user32.RegisterClassW.restype = wintypes.ATOM
        self._user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        self._user32.UnregisterClassW.restype = wintypes.BOOL
        self._user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
            wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]
        self._user32.CreateWindowExW.restype = wintypes.HWND
        self._user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self._user32.DefWindowProcW.restype = ctypes.c_ssize_t
        self._user32.DestroyWindow.argtypes = [wintypes.HWND]
        self._user32.DestroyWindow.restype = wintypes.BOOL
        self._user32.IsWindow.argtypes = [wintypes.HWND]
        self._user32.IsWindow.restype = wintypes.BOOL
        self._user32.PostQuitMessage.argtypes = [ctypes.c_int]
        self._user32.PostQuitMessage.restype = None
        self._user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self._user32.PostMessageW.restype = wintypes.BOOL
        self._user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        self._user32.GetMessageW.restype = ctypes.c_int
        self._user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        self._user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        self._user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
        self._user32.LoadIconW.restype = wintypes.HICON
        self._user32.CreatePopupMenu.restype = wintypes.HMENU
        self._user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
        self._user32.AppendMenuW.restype = wintypes.BOOL
        self._user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                                ctypes.c_int, wintypes.HWND, wintypes.LPVOID]
        self._user32.TrackPopupMenu.restype = wintypes.UINT
        self._user32.DestroyMenu.argtypes = [wintypes.HMENU]
        self._user32.DestroyMenu.restype = wintypes.BOOL
        self._user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self._user32.GetCursorPos.argtypes = [ctypes.c_void_p]
        self._shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.c_void_p]
        self._shell32.Shell_NotifyIconW.restype = wintypes.BOOL

    def _icon_data(self, flags: int):
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(data)
        data.hWnd = self._hwnd
        data.uID = 1
        data.uFlags = flags
        if flags & self.NIF_MESSAGE:
            data.uCallbackMessage = self.WM_TRAY
        if flags & self.NIF_ICON:
            icon_resource = ctypes.cast(ctypes.c_void_p(self.IDI_APPLICATION), wintypes.LPCWSTR)
            data.hIcon = self._user32.LoadIconW(None, icon_resource)
        if flags & self.NIF_TIP:
            data.szTip = ("is-gpt-nerfed | " + self._status)[:127]
        return data

    def _shell(self, message: int, data) -> bool:
        if not self._shell32.Shell_NotifyIconW(message, ctypes.byref(data)):
            code = ctypes.get_last_error()
            if code:
                raise ctypes.WinError(code)
            return False
        return True

    def _window_proc(self, hwnd, message, wparam, lparam):
        if message == self.WM_TRAY:
            mouse_message = int(lparam) & 0xFFFF
            if mouse_message in (self.WM_LBUTTONUP, self.WM_LBUTTONDBLCLK):
                self.on_action("show")
            elif mouse_message in (self.WM_RBUTTONUP, self.WM_CONTEXTMENU):
                self._show_menu(hwnd)
            return 0
        if message == self.WM_DISPATCH:
            self._drain_commands()
            return 0
        if message == self.WM_COMMAND:
            command_id = int(wparam) & 0xFFFF
            if command_id == self.ID_SHOW:
                self.on_action("show")
            elif command_id == self.ID_QUIT:
                self.on_action("quit")
            return 0
        if message == self.WM_CLOSE:
            self._remove_icon()
            self._user32.DestroyWindow(hwnd)
            return 0
        if message == self.WM_DESTROY:
            self._user32.PostQuitMessage(0)
            return 0
        return self._user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _show_menu(self, hwnd) -> None:
        menu = self._user32.CreatePopupMenu()
        if not menu:
            return
        try:
            self._user32.AppendMenuW(menu, self.MF_STRING, self.ID_SHOW, "Open is-gpt-nerfed")
            self._user32.AppendMenuW(menu, self.MF_SEPARATOR, 0, None)
            self._user32.AppendMenuW(menu, self.MF_STRING, self.ID_QUIT, "Quit")
            point = wintypes.POINT()
            self._user32.GetCursorPos(ctypes.byref(point))
            self._user32.SetForegroundWindow(hwnd)
            command_id = self._user32.TrackPopupMenu(
                menu, self.TPM_RETURNCMD | self.TPM_RIGHTBUTTON | self.TPM_BOTTOMALIGN,
                point.x, point.y, 0, hwnd, None,
            )
            if command_id == self.ID_SHOW:
                self.on_action("show")
            elif command_id == self.ID_QUIT:
                self.on_action("quit")
            self._user32.PostMessageW(hwnd, self.WM_NULL, 0, 0)
        finally:
            self._user32.DestroyMenu(menu)

    def _drain_commands(self) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return
            if command[0] == "status" and self._added:
                data = self._icon_data(self.NIF_TIP)
                self._shell(self.NIM_MODIFY, data)
            elif command[0] == "notify" and self._added:
                _, title, message = command
                data = self._icon_data(self.NIF_INFO)
                data.szInfoTitle = title[:63]
                data.szInfo = message[:255]
                data.dwInfoFlags = self.NIIF_INFO
                data.uTimeoutOrVersion = 5000
                self._shell(self.NIM_MODIFY, data)

    def _remove_icon(self) -> None:
        if not self._added:
            return
        try:
            data = self._icon_data(0)
            self._shell(self.NIM_DELETE, data)
        except Exception:
            pass
        self._added = False

    def _message_loop(self) -> None:
        try:
            self._load_api()

            class WNDCLASSW(ctypes.Structure):
                _fields_ = [
                    ("style", wintypes.UINT),
                    ("lpfnWndProc", ctypes.c_void_p),
                    ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE),
                    ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR),
                    ("lpszClassName", wintypes.LPCWSTR),
                ]

            # LRESULT is pointer-sized on both 32-bit and 64-bit Windows.
            wndproc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                              wintypes.WPARAM, wintypes.LPARAM)
            self._wndproc_callback = wndproc_type(self._window_proc)
            instance = self._kernel32.GetModuleHandleW(None)
            self._instance = instance
            window_class = WNDCLASSW()
            window_class.lpfnWndProc = ctypes.cast(self._wndproc_callback, ctypes.c_void_p).value
            window_class.hInstance = instance
            window_class.lpszClassName = self._class_name
            atom = self._user32.RegisterClassW(ctypes.byref(window_class))
            if not atom and ctypes.get_last_error() != 1410:  # class already registered
                raise ctypes.WinError(ctypes.get_last_error())
            self._class_registered = bool(atom) or ctypes.get_last_error() == 1410

            hwnd = self._user32.CreateWindowExW(0, self._class_name, self._class_name, 0,
                                                0, 0, 0, 0, None, None, instance, None)
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            with self._lock:
                self._hwnd = hwnd
                should_stop = self._stop_requested
            if should_stop:
                self._user32.PostMessageW(hwnd, self.WM_CLOSE, 0, 0)
            else:
                data = self._icon_data(self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP)
                if not self._shell(self.NIM_ADD, data):
                    raise TrayUnavailable("Windows did not add the notification area icon.")
                self._added = True
                self.ready = True

            message = wintypes.MSG()
            while True:
                result = self._user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    break
                self._user32.TranslateMessage(ctypes.byref(message))
                self._user32.DispatchMessageW(ctypes.byref(message))
        except Exception as exc:
            self.error = str(exc)
            self.failed = True
        finally:
            self._remove_icon()
            with self._lock:
                hwnd = self._hwnd
            if hwnd and self._user32 is not None:
                try:
                    if self._user32.IsWindow(hwnd):
                        self._user32.DestroyWindow(hwnd)
                except Exception:
                    pass
            if self._class_registered and self._user32 is not None:
                try:
                    if self._user32.UnregisterClassW(self._class_name, self._instance):
                        self._class_registered = False
                except Exception:
                    pass
            self.ready = False
            with self._lock:
                self._hwnd = None
