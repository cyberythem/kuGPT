from __future__ import annotations

import ctypes
import os
import queue
import threading
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from .engine import TextEngine


WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WM_KEYDOWN, WM_KEYUP, WM_CHAR = 0x0100, 0x0101, 0x0102
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105
WM_GETTEXTLENGTH = 0x000E
MOUSE_CLICKS = {0x0201, 0x0204, 0x0207, 0x020B}
LLKHF_INJECTED = 0x10
VK_PACKET = 0xE7
SELF_INJECTION_MARKER = 0x4B55475054
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
user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetClassNameW.restype = ctypes.c_int
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageTimeoutW.argtypes = (
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
)
user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)


EXCLUDED_PROCESSES = {
    "1password.exe", "bitwarden.exe", "credentialuibroker.exe", "keepass.exe",
    "keepassxc.exe", "lastpass.exe", "logonui.exe",
}
CONTROL_KEYS = {VK_CONTROL, 0xA2, 0xA3}
ALT_KEYS = {VK_MENU, 0xA4, 0xA5}
WINDOWS_KEYS = {VK_LWIN, VK_RWIN}
MODIFIER_KEYS = CONTROL_KEYS | ALT_KEYS | WINDOWS_KEYS | {0x10, 0xA0, 0xA1}


@dataclass
class UndoRecord:
    original: str
    replacement: str


class KeyboardDaemon:
    def __init__(self, engine: TextEngine, pause_file: Path, accepted_words_file: Path | None = None):
        self.engine = engine
        self.pause_file = Path(pause_file)
        self.accepted_words_file = Path(accepted_words_file) if accepted_words_file else None
        self.hook = None
        self.mouse_hook = None
        self.last_window = None
        self.context_unknown = True
        self.last_undo: UndoRecord | None = None
        self.last_correction: UndoRecord | None = None
        self.rewrite_backspaces = 0
        self.pending_undo: tuple[UndoRecord, int] | None = None
        self.swallowed_keys: set[int] = set()
        self.pressed_keys: set[int] = set()
        self.callback = HOOKPROC(self._callback)
        self.mouse_callback = HOOKPROC(self._mouse_callback)
        self.word_save_queue: queue.SimpleQueue[str] = queue.SimpleQueue()
        if self.accepted_words_file:
            threading.Thread(target=self._save_words, daemon=True).start()

    def run(self) -> None:
        self.hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self.callback, kernel32.GetModuleHandleW(None), 0)
        if not self.hook:
            raise ctypes.WinError(ctypes.get_last_error())
        self.mouse_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self.mouse_callback, kernel32.GetModuleHandleW(None), 0)
        if not self.mouse_hook:
            user32.UnhookWindowsHookEx(self.hook)
            self.hook = None
            raise ctypes.WinError(ctypes.get_last_error())
        message = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            user32.UnhookWindowsHookEx(self.hook)
            self.hook = None
            user32.UnhookWindowsHookEx(self.mouse_hook)
            self.mouse_hook = None

    def _next(self, code: int, wparam: int, lparam: int) -> int:
        return user32.CallNextHookEx(self.hook, code, wparam, lparam)

    def _mouse_callback(self, code: int, wparam: int, lparam: int) -> int:
        if code >= 0 and wparam in MOUSE_CLICKS:
            self.engine.reset_context()
            self.context_unknown = True
            self.last_undo = None
            self.last_correction = None
        return user32.CallNextHookEx(self.mouse_hook, code, wparam, lparam)

    def _callback(self, code: int, wparam: int, lparam: int) -> int:
        try:
            if code < 0:
                return self._next(code, wparam, lparam)
            data = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if data.flags & LLKHF_INJECTED and data.dwExtraInfo == SELF_INJECTION_MARKER:
                return self._next(code, wparam, lparam)
            vk = int(data.vkCode)
            is_down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
            is_up = wparam in (WM_KEYUP, WM_SYSKEYUP)
            if is_up:
                self.pressed_keys.discard(vk)
                if vk in CONTROL_KEYS | ALT_KEYS and self.pending_undo and not self.pressed_keys.intersection(CONTROL_KEYS | ALT_KEYS):
                    undo, window = self.pending_undo
                    self.pending_undo = None
                    timer = threading.Timer(0.02, self._finish_undo, args=(undo, window))
                    timer.daemon = True
                    timer.start()
            if is_up and vk in self.swallowed_keys:
                self.swallowed_keys.remove(vk)
                return 1
            if not is_down:
                return self._next(code, wparam, lparam)
            self.pressed_keys.add(vk)

            foreground = user32.GetForegroundWindow()
            if foreground != self.last_window:
                self.last_window = foreground
                self.engine.reset_context()
                self.context_unknown = True
                self.last_undo = None
                self.last_correction = None
            if self.pause_file.exists() or sensitive_target(foreground):
                self.engine.reset_context()
                self.context_unknown = True
                self.last_undo = None
                self.last_correction = None
                return self._next(code, wparam, lparam)

            if self.context_unknown and vk not in CONTROL_KEYS | ALT_KEYS | WINDOWS_KEYS:
                self.engine.reset_context(start_of_sentence=is_known_document_start())
                self.context_unknown = False

            if vk == VK_BACK and self.pressed_keys.intersection(CONTROL_KEYS) and self.pressed_keys.intersection(ALT_KEYS):
                if self.last_undo:
                    self.swallowed_keys.add(vk)
                    self._accept_original(self.last_undo)
                    self.pending_undo = (self.last_undo, foreground)
                    self.last_undo = None
                    self.last_correction = None
                    self.engine.reset_context()
                    return 1
                return self._next(code, wparam, lparam)
            if vk in MODIFIER_KEYS:
                if vk in CONTROL_KEYS | ALT_KEYS | WINDOWS_KEYS:
                    self.engine.reset_context()
                    self.context_unknown = True
                return self._next(code, wparam, lparam)
            if self.pressed_keys.intersection(CONTROL_KEYS | ALT_KEYS | WINDOWS_KEYS):
                if vk == 0x5A and self.last_correction and self.pressed_keys.intersection(CONTROL_KEYS):
                    self._accept_original(self.last_correction)
                self.engine.reset_context()
                self.context_unknown = True
                self.last_undo = None
                self.last_correction = None
                return self._next(code, wparam, lparam)
            if vk == VK_BACK:
                if self.last_correction:
                    self.rewrite_backspaces += 1
                    if self.rewrite_backspaces >= 2:
                        self._accept_original(self.last_correction)
                        self.last_correction = None
                had_word = bool(self.engine.current_word)
                self.engine.backspace()
                if not had_word:
                    self.context_unknown = True
                self.last_undo = None
                return self._next(code, wparam, lparam)

            boundary = get_boundary(vk, data.scanCode)
            if boundary:
                kind, punctuation = boundary
                plan = self.engine.complete_boundary(kind, punctuation)
                self.swallowed_keys.add(vk)
                if plan:
                    send_replacement(plan.delete_count, plan.insert_text)
                    record = UndoRecord(plan.original_text, plan.insert_text)
                    self.last_undo = record
                    self.last_correction = record
                    self.rewrite_backspaces = 0
                    return 1
                self.last_undo = None
                self.last_correction = None
                send_replacement(0, {"space": " ", "enter": "\r"}.get(kind, punctuation))
                return 1

            typed = translate_key(vk, data.scanCode)
            if typed:
                self.engine.type_character(typed)
                self.swallowed_keys.add(vk)
                send_replacement(0, typed)
                self.last_undo = None
                self.last_correction = None
                return 1
            elif vk not in (0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5):
                self.engine.reset_context()
                self.context_unknown = True
            self.last_undo = None
            self.last_correction = None
            return self._next(code, wparam, lparam)
        except Exception:
            return self._next(code, wparam, lparam)

    def _finish_undo(self, undo: UndoRecord, window: int) -> None:
        if user32.GetForegroundWindow() == window:
            try:
                send_replacement(len(undo.replacement), undo.original)
            except Exception:
                pass

    def _accept_original(self, record: UndoRecord) -> None:
        original_word = record.original.rstrip(" \r.!?,;:")
        accepted = self.engine.accept_word(original_word)
        if accepted and self.accepted_words_file:
            self.word_save_queue.put(accepted)

    def _save_words(self) -> None:
        while True:
            word = self.word_save_queue.get()
            try:
                self.accepted_words_file.parent.mkdir(parents=True, exist_ok=True)
                with self.accepted_words_file.open("a", encoding="utf-8") as stream:
                    stream.write(word + "\n")
            except OSError:
                pass


def get_boundary(vk: int, scan_code: int) -> tuple[str, str] | None:
    if vk == VK_SPACE:
        return "space", ""
    if vk == VK_RETURN:
        return "enter", ""
    value = translate_key(vk, scan_code)
    if value is not None and value in ".!?,;:":
        return "punctuation", value
    return None


def translate_key(vk: int, scan_code: int) -> str | None:
    if vk == VK_PACKET and 32 <= scan_code <= 0xFFFF:
        return chr(scan_code)
    state = (ctypes.c_ubyte * 256)()
    if not user32.GetKeyboardState(state):
        return None
    layout = user32.GetKeyboardLayout(0)
    scan = scan_code or user32.MapVirtualKeyExW(vk, 0, layout)
    buffer = ctypes.create_unicode_buffer(8)
    result = user32.ToUnicodeEx(vk, scan, state, buffer, len(buffer), 0, layout)
    return buffer.value[0] if result == 1 and buffer.value and ord(buffer.value[0]) >= 32 else None


def send_replacement(delete_count: int, text: str) -> None:
    target = focused_window()
    if not target:
        raise RuntimeError("No focused window to edit")
    for _ in range(delete_count):
        send_message(target, WM_KEYDOWN, VK_BACK)
        send_message(target, WM_KEYUP, VK_BACK)
    for char in text:
        if char == "\r":
            send_message(target, WM_KEYDOWN, VK_RETURN)
            send_message(target, WM_KEYUP, VK_RETURN)
        else:
            send_message(target, WM_CHAR, ord(char))


def send_message(target: int, message: int, value: int) -> None:
    result = ctypes.c_size_t()
    if not user32.SendMessageTimeoutW(target, message, value, 1, 0x2, 100, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())


def focused_window() -> int | None:
    foreground = user32.GetForegroundWindow()
    if not foreground:
        return None
    process_id = wintypes.DWORD()
    thread_id = user32.GetWindowThreadProcessId(foreground, ctypes.byref(process_id))
    info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
    if user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)) and info.hwndFocus:
        return info.hwndFocus
    return foreground


def is_known_document_start() -> bool:
    """Only infer a new sentence when a standard native editor is empty."""
    target = focused_window()
    if not target:
        return False
    class_name = ctypes.create_unicode_buffer(256)
    if not user32.GetClassNameW(target, class_name, len(class_name)):
        return False
    editor_class = class_name.value.casefold()
    if not (editor_class == "edit" or editor_class.startswith("richedit")):
        return False
    length = ctypes.c_size_t()
    if not user32.SendMessageTimeoutW(
        target, WM_GETTEXTLENGTH, 0, 0, 0x2, 50, ctypes.byref(length),
    ):
        return False
    return length.value == 0


def key_input(vk: int, flags: int = 0) -> INPUT:
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, dwFlags=flags, dwExtraInfo=SELF_INJECTION_MARKER))


def unicode_input(char: str, flags: int = 0) -> INPUT:
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wScan=ord(char), dwFlags=KEYEVENTF_UNICODE | flags, dwExtraInfo=SELF_INJECTION_MARKER))


def sensitive_target(window: int) -> bool:
    if not window:
        return True
    process_id = wintypes.DWORD()
    thread_id = user32.GetWindowThreadProcessId(window, ctypes.byref(process_id))
    name = process_name(process_id.value)
    if not name or name.casefold() in EXCLUDED_PROCESSES:
        return True
    info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
    if user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)) and info.hwndFocus:
        password_character = ctypes.c_size_t()
        if not user32.SendMessageTimeoutW(
            info.hwndFocus, EM_GETPASSWORDCHAR, 0, 0, 0x2, 50,
            ctypes.byref(password_character),
        ):
            return True
        if password_character.value:
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

