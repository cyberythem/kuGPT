from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from .engine import EditPlan, TextEngine


WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105
LLKHF_INJECTED = 0x10
VK_BACK, VK_RETURN, VK_SPACE = 0x08, 0x0D, 0x20
VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN = 0x11, 0x12, 0x5B, 0x5C
INPUT_KEYBOARD, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 1, 0x0002, 0x0004
EM_GETPASSWORDCHAR = 0x00D2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetKeyboardLayout.restype = wintypes.HANDLE
user32.SendMessageW.restype = ctypes.c_ssize_t
kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)


EXCLUDED_PROCESSES = {
    "1password.exe", "bitwarden.exe", "credentialuibroker.exe", "keepass.exe",
    "keepassxc.exe", "lastpass.exe", "logonui.exe",
}


@dataclass
class UndoRecord:
    original: str
    replacement: str


class KeyboardDaemon:
    def __init__(self, engine: TextEngine, pause_file: Path):
        self.engine = engine
        self.pause_file = Path(pause_file)
        self.hook = None
        self.last_window = None
        self.last_undo: UndoRecord | None = None
        self.swallowed_keys: set[int] = set()
        self.callback = HOOKPROC(self._callback)

    def run(self) -> None:
        self.hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self.callback, kernel32.GetModuleHandleW(None), 0)
        if not self.hook:
            raise ctypes.WinError(ctypes.get_last_error())
        message = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            user32.UnhookWindowsHookEx(self.hook)
            self.hook = None

    def _next(self, code: int, wparam: int, lparam: int) -> int:
        return user32.CallNextHookEx(self.hook, code, wparam, lparam)

    def _callback(self, code: int, wparam: int, lparam: int) -> int:
        try:
            if code < 0:
                return self._next(code, wparam, lparam)
            data = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if data.flags & LLKHF_INJECTED:
                return self._next(code, wparam, lparam)
            vk = int(data.vkCode)
            is_down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
            is_up = wparam in (WM_KEYUP, WM_SYSKEYUP)
            if is_up and vk in self.swallowed_keys:
                self.swallowed_keys.remove(vk)
                return 1
            if not is_down:
                return self._next(code, wparam, lparam)

            foreground = user32.GetForegroundWindow()
            if foreground != self.last_window:
                self.last_window = foreground
                self.engine.reset_context()
                self.last_undo = None
            if self.pause_file.exists() or sensitive_target(foreground):
                self.engine.reset_context()
                self.last_undo = None
                return self._next(code, wparam, lparam)

            if vk == VK_BACK and pressed(VK_CONTROL) and pressed(VK_MENU):
                if self.last_undo:
                    self.swallowed_keys.add(vk)
                    send_replacement(len(self.last_undo.replacement), self.last_undo.original)
                    self.last_undo = None
                    self.engine.reset_context()
                    return 1
                return self._next(code, wparam, lparam)
            if any(pressed(key) for key in (VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN)):
                self.engine.reset_context()
                self.last_undo = None
                return self._next(code, wparam, lparam)
            if vk == VK_BACK:
                self.engine.backspace()
                self.last_undo = None
                return self._next(code, wparam, lparam)

            boundary = get_boundary(vk, data.scanCode)
            if boundary:
                kind, punctuation = boundary
                plan = self.engine.complete_boundary(kind, punctuation)
                if plan:
                    self.swallowed_keys.add(vk)
                    send_replacement(plan.delete_count, plan.insert_text)
                    self.last_undo = UndoRecord(plan.original_text, plan.insert_text)
                    return 1
                self.last_undo = None
                return self._next(code, wparam, lparam)

            typed = translate_key(vk, data.scanCode)
            if typed:
                self.engine.type_character(typed)
            elif vk not in (0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5):
                self.engine.reset_context()
            self.last_undo = None
            return self._next(code, wparam, lparam)
        except Exception:
            return self._next(code, wparam, lparam)


def pressed(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def get_boundary(vk: int, scan_code: int) -> tuple[str, str] | None:
    if vk == VK_SPACE:
        return "space", ""
    if vk == VK_RETURN:
        return "enter", ""
    value = translate_key(vk, scan_code)
    if value in ".!?,;:":
        return "punctuation", value
    return None


def translate_key(vk: int, scan_code: int) -> str | None:
    state = (ctypes.c_ubyte * 256)()
    if not user32.GetKeyboardState(state):
        return None
    layout = user32.GetKeyboardLayout(0)
    scan = scan_code or user32.MapVirtualKeyExW(vk, 0, layout)
    buffer = ctypes.create_unicode_buffer(8)
    result = user32.ToUnicodeEx(vk, scan, state, buffer, len(buffer), 0, layout)
    return buffer.value[0] if result == 1 and buffer.value and not buffer.value[0].iscntrl() else None


def send_replacement(delete_count: int, text: str) -> None:
    values: list[INPUT] = []
    for _ in range(delete_count):
        values.extend((key_input(VK_BACK), key_input(VK_BACK, KEYEVENTF_KEYUP)))
    for char in text:
        if char == "\r":
            values.extend((key_input(VK_RETURN), key_input(VK_RETURN, KEYEVENTF_KEYUP)))
        else:
            values.extend((unicode_input(char), unicode_input(char, KEYEVENTF_KEYUP)))
    if values:
        array = (INPUT * len(values))(*values)
        if user32.SendInput(len(values), array, ctypes.sizeof(INPUT)) != len(values):
            raise ctypes.WinError(ctypes.get_last_error())


def key_input(vk: int, flags: int = 0) -> INPUT:
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, dwFlags=flags))


def unicode_input(char: str, flags: int = 0) -> INPUT:
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wScan=ord(char), dwFlags=KEYEVENTF_UNICODE | flags))


def sensitive_target(window: int) -> bool:
    if not window:
        return True
    process_id = wintypes.DWORD()
    thread_id = user32.GetWindowThreadProcessId(window, ctypes.byref(process_id))
    if process_name(process_id.value).casefold() in EXCLUDED_PROCESSES:
        return True
    info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
    if user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)) and info.hwndFocus:
        if user32.SendMessageW(info.hwndFocus, EM_GETPASSWORDCHAR, 0, 0):
            return True
    return False


def process_name(process_id: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return os.path.basename(buffer.value)
        return ""
    finally:
        kernel32.CloseHandle(handle)

