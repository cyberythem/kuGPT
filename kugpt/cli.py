from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from .engine import TextEngine, correct_text
from .spelling import SymSpell


DATA_DIR = Path(os.environ.get("KUGPT_DATA_DIR", Path(os.environ.get("LOCALAPPDATA", Path.home())) / "kuGPT"))
PID_FILE = DATA_DIR / "kugpt.pid"
PAUSE_FILE = DATA_DIR / "paused"
ROOT = Path(__file__).resolve().parents[1]
DICTIONARY = ROOT / "data" / "frequency_dictionary_en_82_765.txt"


def main(arguments: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if arguments is None else arguments)
    command = (args.pop(0) if args else "help").casefold()
    try:
        if command == "run": return run_daemon()
        if command == "start": return start()
        if command == "stop": return stop(True)
        if command == "restart": stop(False); return start()
        if command == "status": return status()
        if command == "pause": return pause()
        if command == "resume": return resume()
        if command == "install": return install()
        if command == "uninstall": return uninstall()
        if command == "doctor": return doctor()
        if command == "check": return check(args)
        if command == "fix": return fix(args)
        if command in ("version", "--version"): print(f"kuGPT {__version__}"); return 0
        if command in ("help", "--help", "-h"): show_help(); return 0
        print(f"Unknown command: {command}", file=sys.stderr); show_help(); return 2
    except Exception as error:
        print(f"kuGPT: {error}", file=sys.stderr)
        return 1


def provider() -> SymSpell:
    return SymSpell(DICTIONARY)


def run_daemon() -> int:
    if os.name != "nt":
        raise RuntimeError("the system-wide keyboard hook currently requires Windows")
    from .windows_hook import KeyboardDaemon
    existing = read_pid()
    if existing and process_running(existing):
        print(f"kuGPT is already running (PID {existing}).", file=sys.stderr)
        return 1
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    try:
        KeyboardDaemon(TextEngine(provider()), PAUSE_FILE).run()
    finally:
        PID_FILE.unlink(missing_ok=True)
    return 0


def start() -> int:
    existing = read_pid()
    if existing and process_running(existing):
        print(f"kuGPT is already running (PID {existing}).")
        return 0
    PID_FILE.unlink(missing_ok=True)
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    executable = pythonw if pythonw.exists() else Path(sys.executable)
    launcher = ROOT / "kugpt_launcher.py"
    flags = 0x00000008 | 0x00000200 | 0x08000000 if os.name == "nt" else 0
    process = subprocess.Popen(
        [str(executable), str(launcher), "run"], cwd=str(ROOT),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    for _ in range(20):
        time.sleep(0.1)
        pid = read_pid()
        if pid and process_running(pid):
            print(f"kuGPT started locally (PID {pid}).")
            return 0
        if process.poll() is not None:
            break
    print("kuGPT failed to start. Run 'kugpt doctor' for diagnostics.", file=sys.stderr)
    return 1


def stop(report: bool) -> int:
    pid = read_pid()
    if not pid or not process_running(pid):
        PID_FILE.unlink(missing_ok=True)
        if report: print("kuGPT is not running.")
        return 0
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False)
    PID_FILE.unlink(missing_ok=True)
    if report: print("kuGPT stopped.")
    return 0


def status() -> int:
    pid = read_pid()
    running = bool(pid and process_running(pid))
    print("Status: " + ("running" if running else "stopped"))
    if running: print(f"PID: {pid}")
    print("Corrections: " + ("paused" if PAUSE_FILE.exists() else "active"))
    print("Processing: local memory only")
    return 0 if running else 1


def pause() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PAUSE_FILE.touch()
    print("kuGPT corrections paused.")
    return 0


def resume() -> int:
    PAUSE_FILE.unlink(missing_ok=True)
    print("kuGPT corrections resumed.")
    return 0


def install() -> int:
    if os.name != "nt": return 1
    import winreg
    command = f'"{Path(sys.executable).with_name("pythonw.exe")}" "{ROOT / "kugpt_launcher.py"}" run'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        winreg.SetValueEx(key, "kuGPT", 0, winreg.REG_SZ, command)
    print("kuGPT installed for this Windows user and enabled at sign-in.")
    return start()


def uninstall() -> int:
    stop(False)
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, "kuGPT")
        except FileNotFoundError:
            pass
    PAUSE_FILE.unlink(missing_ok=True)
    print("kuGPT startup was removed and the daemon was stopped.")
    return 0


def doctor() -> int:
    print("Windows: " + ("ok" if os.name == "nt" else "unsupported"))
    print(f"Runtime: Python {sys.version.split()[0]} ({Path(sys.executable)})")
    print(f"Data directory: {DATA_DIR}")
    try:
        spelling = provider()
        print(f"SymSpell dictionary: ok ({len(spelling.words):,} English words)")
        dictionary_ok = True
    except Exception as error:
        print(f"SymSpell dictionary: unavailable ({error})")
        dictionary_ok = False
    print("Password fields: standard Windows fields excluded")
    print("Password managers: excluded")
    return 0 if os.name == "nt" and dictionary_ok else 1


def check(words: list[str]) -> int:
    if not words:
        print("Usage: kugpt check <word> [word ...]", file=sys.stderr)
        return 2
    spelling = provider()
    for word in words:
        suggestion = spelling.suggest(word)
        print(f"{word} -> {suggestion or '(correct/no suggestion)'}")
    return 0


def fix(parts: list[str]) -> int:
    if not parts:
        print("Usage: kugpt fix <text>", file=sys.stderr)
        return 2
    text = " ".join(parts)
    print(correct_text(TextEngine(provider()), text + " ").rstrip())
    return 0


def read_pid() -> int | None:
    try: return int(PID_FILE.read_text(encoding="ascii").strip())
    except (OSError, ValueError): return None


def process_running(pid: int) -> bool:
    if os.name != "nt":
        try: os.kill(pid, 0); return True
        except OSError: return False
    import ctypes
    handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
    if not handle: return False
    try: return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == 0x102
    finally: ctypes.windll.kernel32.CloseHandle(handle)


def show_help() -> None:
    print("kuGPT - private, local writing correction for Windows\n")
    print("  kugpt start|stop|restart   Control system-wide correction")
    print("  kugpt pause|resume         Temporarily disable/enable it")
    print("  kugpt status|doctor        Inspect the local service")
    print("  kugpt check WORD [...]     Preview SymSpell suggestions")
    print("  kugpt fix TEXT             Preview a corrected sentence")
    print("  kugpt uninstall            Remove startup and stop")
    print("\nUndo the latest correction: Ctrl+Alt+Backspace")

