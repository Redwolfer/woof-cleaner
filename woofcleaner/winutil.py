"""Thin Windows helpers (ctypes / winreg). Everything degrades gracefully off-Windows."""
from __future__ import annotations

import os
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    import winreg
    from ctypes import wintypes

_HIVES = {}
if IS_WINDOWS:
    _HIVES = {
        "HKCU": winreg.HKEY_CURRENT_USER,
        "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
        "HKLM": winreg.HKEY_LOCAL_MACHINE,
        "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
    }


def default_env() -> dict[str, str]:
    """Environment used to expand %VARS% in rules (keys are upper-case)."""
    env = {k.upper(): v for k, v in os.environ.items()}
    local = env.get("LOCALAPPDATA", "")
    profile = env.get("USERPROFILE", "")
    appdata = env.get("APPDATA", "")
    env.setdefault("COMMONAPPDATA", env.get("PROGRAMDATA", ""))
    env.setdefault("LOCALLOWAPPDATA", os.path.join(os.path.dirname(local), "LocalLow") if local else "")
    env.setdefault("RECENT", os.path.join(appdata, "Microsoft", "Windows", "Recent") if appdata else "")
    env.setdefault("DOCUMENTS", os.path.join(profile, "Documents") if profile else "")
    env.setdefault("DESKTOP", os.path.join(profile, "Desktop") if profile else "")
    env.setdefault("SYSTEMDIRECTORY", os.path.join(env.get("WINDIR", ""), "System32"))
    return env


def windows_version() -> tuple[int, int]:
    if not IS_WINDOWS:
        return (0, 0)
    v = sys.getwindowsversion()
    return (v.major, v.minor)


def is_admin() -> bool:
    if not IS_WINDOWS:
        return os.geteuid() == 0
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def running_processes() -> set[str]:
    """Lower-case image names of running processes."""
    if not IS_WINDOWS:
        return set()
    try:
        out = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=15,
            creationflags=0x08000000,
        ).stdout
    except Exception:
        return set()
    names = set()
    for line in out.splitlines():
        if line.startswith('"'):
            names.add(line.split('","')[0].strip('"').lower())
    return names


# ---- registry -------------------------------------------------------------

def _split_reg(path: str):
    hive, _, sub = path.partition("\\")
    return _HIVES.get(hive.upper()), sub


def reg_key_exists(path: str) -> bool:
    if not IS_WINDOWS:
        return False
    hive, sub = _split_reg(path)
    if hive is None:
        return False
    try:
        winreg.CloseKey(winreg.OpenKey(hive, sub))
        return True
    except OSError:
        return False


def reg_value_exists(path: str, value: str) -> bool:
    if not IS_WINDOWS:
        return False
    hive, sub = _split_reg(path)
    try:
        with winreg.OpenKey(hive, sub) as k:
            winreg.QueryValueEx(k, value)
        return True
    except (OSError, TypeError):
        return False


def reg_dump(hive, sub: str) -> dict:
    """Recursively dump a key to a JSON-able dict (for the pre-delete backup)."""
    out = {"values": {}, "subkeys": {}}
    with winreg.OpenKey(hive, sub) as k:
        i = 0
        while True:
            try:
                n, v, t = winreg.EnumValue(k, i)
            except OSError:
                break
            out["values"][n] = [t, v.hex() if isinstance(v, bytes) else v]
            i += 1
        i = 0
        while True:
            try:
                s = winreg.EnumKey(k, i)
            except OSError:
                break
            out["subkeys"][s] = reg_dump(hive, sub + "\\" + s)
            i += 1
    return out


def reg_delete(path: str, value: str | None) -> None:
    hive, sub = _split_reg(path)
    if value:
        with winreg.OpenKey(hive, sub, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, value)
    else:
        _reg_delete_tree(hive, sub)


def _reg_delete_tree(hive, sub: str) -> None:
    with winreg.OpenKey(hive, sub, 0, winreg.KEY_ALL_ACCESS) as k:
        while True:
            try:
                child = winreg.EnumKey(k, 0)
            except OSError:
                break
            _reg_delete_tree(hive, sub + "\\" + child)
    winreg.DeleteKey(hive, sub)


# ---- built-in actions -----------------------------------------------------

class _RBInfo(ctypes.Structure if IS_WINDOWS else object):
    if IS_WINDOWS:
        _fields_ = [("cbSize", wintypes.DWORD), ("size", ctypes.c_longlong), ("items", ctypes.c_longlong)]


def recycle_bin_info() -> tuple[int, int]:
    """(bytes, item_count) across all drives."""
    if not IS_WINDOWS:
        return (0, 0)
    info = _RBInfo()
    info.cbSize = ctypes.sizeof(info)
    if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) != 0:
        return (0, 0)
    return (info.size, info.items)


def empty_recycle_bin() -> None:
    # SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
    rc = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x7)
    if rc != 0:
        raise OSError(f"SHEmptyRecycleBinW failed: 0x{rc & 0xFFFFFFFF:08X}")


def flush_dns() -> None:
    ctypes.windll.dnsapi.DnsFlushResolverCache()


def clear_clipboard() -> None:
    u32 = ctypes.windll.user32
    if not u32.OpenClipboard(None):
        raise OSError("clipboard is busy")
    try:
        u32.EmptyClipboard()
    finally:
        u32.CloseClipboard()


def clear_recent_documents() -> None:
    # SHARD_PIDL (1) with a NULL pointer clears the Recent Documents list.
    ctypes.windll.shell32.SHAddToRecentDocs(1, None)


# ---- processes / shell ----------------------------------------------------

def split_command_line(cmd: str) -> tuple[str, str]:
    """Split an uninstall-style command line into (exe, args). Handles unquoted paths with spaces."""
    cmd = cmd.strip()
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        if end > 0:
            return cmd[1:end], cmd[end + 1:].strip()
    low = cmd.lower()
    for ext in (".exe", ".cmd", ".bat", ".com"):
        i = low.find(ext)
        if i > 0:
            return cmd[: i + len(ext)], cmd[i + len(ext):].strip()
    exe, _, args = cmd.partition(" ")
    return exe, args


if IS_WINDOWS:
    class _SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
        ]


def shell_execute(exe: str, args: str = "", verb: str = "open", wait: bool = True,
                  cwd: str | None = None, show: int = 1) -> int | None:
    """ShellExecuteEx: honours UAC manifests (prompts when the target needs admin). Returns exit code if waited."""
    ctypes.windll.ole32.CoInitializeEx(None, 0x2 | 0x4)  # STA, no OLE1; harmless if already initialised
    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb, info.lpFile, info.lpParameters = verb, exe, args or None
    info.lpDirectory, info.nShow = cwd, show
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        err = ctypes.get_last_error()
        if err == 1223:
            raise OSError("cancelled at the UAC prompt")
        raise ctypes.WinError(err)
    if not info.hProcess:
        return None
    try:
        if not wait:
            return None
        ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        code = wintypes.DWORD()
        ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value
    finally:
        ctypes.windll.kernel32.CloseHandle(info.hProcess)


def run_powershell(script: str, timeout: int = 600) -> str:
    """Run a PowerShell script (UTF-8 output) and return stdout. Raises on non-zero exit."""
    import base64
    full = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;$ProgressPreference='SilentlyContinue';" + script
    enc = base64.b64encode(full.encode("utf-16-le")).decode()
    r = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc],
        capture_output=True, timeout=timeout, creationflags=0x08000000,
    )
    out = r.stdout.decode("utf-8", "replace")
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip() or f"powershell exit {r.returncode}")
    return out


def ps_json(script: str, timeout: int = 600) -> list[dict]:
    """Run a script ending in ConvertTo-Json; always returns a list."""
    import json
    out = run_powershell(script, timeout).strip()
    if not out:
        return []
    data = json.loads(out)
    return data if isinstance(data, list) else [data]


def relaunch_as_admin(args: str, cwd: str) -> None:
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        w = exe[:-10] + "pythonw.exe"
        exe = w if os.path.exists(w) else exe
    shell_execute(exe, args, verb="runas", wait=False, cwd=cwd)


# ---- recycle bin -----------------------------------------------------------

if IS_WINDOWS:
    class _SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND), ("wFunc", ctypes.c_uint), ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR),
        ]


def send_to_recycle_bin(paths: list[str]) -> None:
    """Delete files/folders to the Recycle Bin (undoable)."""
    if not paths:
        return
    op = _SHFILEOPSTRUCTW()
    op.wFunc = 3  # FO_DELETE
    op.pFrom = "\0".join(os.path.abspath(p) for p in paths) + "\0\0"
    # FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI
    op.fFlags = 0x0004 | 0x0010 | 0x0040 | 0x0400
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0:
        raise OSError(f"SHFileOperation failed with code 0x{rc:X}")
    if op.fAnyOperationsAborted:
        raise OSError("operation aborted")


def reg_open_ex(path: str, access: int, view: int = 0):
    hive, sub = _split_reg(path)
    return winreg.OpenKey(hive, sub, 0, access | view)
