"""Registry cleaner: finds entries that point to files or folders that no longer exist.

Modelled on CCleaner's Registry categories (custom-clean.info.registry.* in its UI): obsolete software,
application paths, startup entries, MUI cache, shared DLLs, help files, sound events, installer folders,
"open with" applications and fonts.

It is deliberately conservative. An entry is only reported when it names an absolute local path whose
drive exists and Windows answers "file not found" (access-denied, network, removable and WindowsApps
paths are never judged). Commands run through rundll32/msiexec/cmd and similar hosts are skipped because
the real target is an argument. Every change is written to a JSON backup first and can be restored.
Windows services, file-type associations and firewall rules are not touched: a wrong guess there can
break Windows.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import winutil

if winutil.IS_WINDOWS:
    import winreg
    V64, V32 = winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY
else:  # pragma: no cover - keeps the module importable for tests elsewhere
    V64, V32 = 0x100, 0x200

CATEGORIES: dict[str, tuple[str, str]] = {
    "software": ("Obsolete software", "Uninstall entries of programs whose uninstaller and folder are gone."),
    "apppaths": ("Application paths", "Registered application paths that point to missing programs."),
    "startup": ("Run at startup", "Startup entries (and their Task Manager switches) for missing programs."),
    "muicache": ("MUI cache", "Cached names of programs that no longer exist."),
    "shareddlls": ("Missing shared DLLs", "Shared library counters for DLL files that no longer exist."),
    "helpfiles": ("Help files", "Help file references to files that no longer exist."),
    "sounds": ("Sound events", "Sound events that play a missing .wav file (the event is set to no sound)."),
    "installer": ("Installer folders", "Windows Installer folder references to folders that no longer exist."),
    "openwith": ("Open with applications", "\"Open with\" programs whose executable is missing."),
    "fonts": ("Fonts", "Font registrations for font files that no longer exist."),
}

UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
APP_PATHS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
RUN = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"
MUICACHE = r"HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\MuiCache"
SHARED = r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\SharedDLLs"
HELP = r"SOFTWARE\Microsoft\Windows\Help"
SOUNDS = r"HKCU\AppEvents\Schemes\Apps"
INSTALLER = r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\Folders"
OPENWITH = r"HKCU\Software\Classes\Applications"
FONTS = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"

# Programs that run something else named in their arguments: the exe itself always exists.
_HOSTS = {"rundll32.exe", "msiexec.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "wscript.exe", "cscript.exe",
          "explorer.exe", "regsvr32.exe", "mshta.exe", "conhost.exe", "dllhost.exe", "svchost.exe"}


@dataclass
class Issue:
    category: str
    problem: str
    path: str               # registry key, e.g. HKCU\Software\...
    value: str | None       # None = the whole key
    op: str                 # delete_key | delete_value | clear_value
    view: int = 0

    @property
    def needs_admin(self) -> bool:
        return self.path.upper().startswith(("HKLM", "HKEY_LOCAL_MACHINE"))

    @property
    def location(self) -> str:
        bits = " (32-bit)" if self.view == V32 else ""
        return self.path + bits + (f"  →  {self.value or '(Default)'}" if self.op != "delete_key" else "")

    @property
    def key(self) -> str:
        return f"{self.op}|{self.view}|{self.path}|{self.value}"


# ---- path checks ---------------------------------------------------------------

def is_missing(path: str, view: int = 0) -> bool:
    """True only when `path` is an absolute local path that certainly does not exist."""
    p = os.path.expandvars((path or "").strip().strip('"')).strip()
    if not p or not re.match(r"^[A-Za-z]:\\", p) or "\\windowsapps\\" in p.lower():
        return False
    if not os.path.exists(p[:3]):
        return False            # removable / unmapped drive: can't judge
    candidates = [p]
    if view == V32:
        windir = os.environ.get("WINDIR", r"C:\Windows")
        low = p.lower()
        if low.startswith((windir + "\\system32\\").lower()):
            candidates.append(windir + "\\SysWOW64\\" + p[len(windir) + 10:])
        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        if low.startswith(pf.lower() + "\\"):
            candidates.append(pf86 + p[len(pf):])
    for c in candidates:
        try:
            os.stat(c)
            return False
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            return False        # access denied, bad name...: not proof of absence
    return True


def exe_of(command: str) -> str | None:
    """The program a command line runs, or None when it can't be judged (relative path, host program)."""
    if not command:
        return None
    exe, _args = winutil.split_command_line(os.path.expandvars(str(command)))
    exe = exe.strip().strip('"')
    if not re.match(r"^[A-Za-z]:\\", exe) or os.path.basename(exe).lower() in _HOSTS:
        return None
    return exe


# ---- scanners ------------------------------------------------------------------

def _scan_software() -> list[Issue]:
    out = []
    for hive, view in (("HKCU", 0), ("HKLM", V64), ("HKLM", V32)):
        base = f"{hive}\\{UNINSTALL}"
        for sub in winutil.reg_subkeys(base, view):
            key = f"{base}\\{sub}"
            vals = {n.lower(): v for n, v, _t in winutil.reg_values(key, view)}
            if vals.get("systemcomponent") == 1 or vals.get("windowsinstaller") == 1:
                continue
            exe = exe_of(vals.get("uninstallstring", ""))
            loc = str(vals.get("installlocation") or "")
            if exe and is_missing(exe, view) and (not loc.strip() or is_missing(loc, view)):
                name = vals.get("displayname") or sub
                out.append(Issue("software", f"{name}: uninstaller is missing ({exe})", key, None, "delete_key", view))
    return out


def _scan_apppaths() -> list[Issue]:
    out = []
    for hive, view in (("HKCU", 0), ("HKLM", V64), ("HKLM", V32)):
        base = f"{hive}\\{APP_PATHS}"
        for sub in winutil.reg_subkeys(base, view):
            key = f"{base}\\{sub}"
            target = winutil.reg_get(key, None, view)
            if isinstance(target, str) and is_missing(target, view):
                out.append(Issue("apppaths", f"{sub}: missing {target}", key, None, "delete_key", view))
    return out


def _scan_startup() -> list[Issue]:
    out = []
    for hive, view, approved in (("HKCU", 0, "Run"), ("HKLM", V64, "Run"), ("HKLM", V32, "Run32")):
        key = f"{hive}\\{RUN}"
        names = set()
        for name, data, _t in winutil.reg_values(key, view):
            names.add(name.lower())
            exe = exe_of(str(data))
            if exe and is_missing(exe, view):
                out.append(Issue("startup", f"{name}: missing {exe}", key, name, "delete_value", view))
        # Task Manager's enable/disable switches left behind for Run values that no longer exist
        appr = f"{hive}\\{APPROVED}\\{approved}"
        for name, _d, _t in winutil.reg_values(appr):
            # names with a backslash (e.g. EPLTarget\P000...) are written by Windows itself, not for Run values
            if name.lower() not in names and "\\" not in name:
                out.append(Issue("startup", f"{name}: startup switch for a removed entry", appr, name, "delete_value"))
    # ... and for Startup-folder shortcuts that were deleted
    env = winutil.default_env()
    for hive, folder in (("HKCU", os.path.join(env.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")),
                         ("HKLM", os.path.join(env.get("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs\StartUp"))):
        appr = f"{hive}\\{APPROVED}\\StartupFolder"
        for name, _d, _t in winutil.reg_values(appr):
            if os.path.isdir(folder) and is_missing(os.path.join(folder, name)):
                out.append(Issue("startup", f"{name}: startup switch for a removed shortcut", appr, name, "delete_value"))
    return out


def _scan_muicache() -> list[Issue]:
    out = []
    for name, _d, _t in winutil.reg_values(MUICACHE):
        m = re.match(r"^(.*\.exe)\.(FriendlyAppName|ApplicationCompany)$", name, re.I)
        if m and is_missing(m.group(1)):
            out.append(Issue("muicache", f"missing {m.group(1)}", MUICACHE, name, "delete_value"))
    return out


def _scan_shareddlls() -> list[Issue]:
    out = []
    for view in (V64, V32):
        for name, _d, _t in winutil.reg_values(SHARED, view):
            if is_missing(name, view):
                out.append(Issue("shareddlls", f"missing {name}", SHARED, name, "delete_value", view))
    return out


def _scan_help() -> list[Issue]:
    out = []
    for hive, view in (("HKCU", 0), ("HKLM", V64), ("HKLM", V32)):
        key = f"{hive}\\{HELP}"
        for name, data, _t in winutil.reg_values(key, view):
            if isinstance(data, str) and data.strip():
                f = os.path.join(os.path.expandvars(data.strip()), name)
                if is_missing(f, view):
                    out.append(Issue("helpfiles", f"missing {f}", key, name, "delete_value", view))
    return out


def _scan_sounds() -> list[Issue]:
    out = []
    for app in winutil.reg_subkeys(SOUNDS):
        for event in winutil.reg_subkeys(f"{SOUNDS}\\{app}"):
            key = f"{SOUNDS}\\{app}\\{event}\\.Current"
            wav = winutil.reg_get(key)
            if isinstance(wav, str) and wav.strip() and is_missing(wav):
                out.append(Issue("sounds", f"{app} / {event}: missing {wav}", key, None, "clear_value"))
    return out


def _scan_installer() -> list[Issue]:
    return [Issue("installer", f"missing folder {name}", INSTALLER, name, "delete_value", V64)
            for name, _d, _t in winutil.reg_values(INSTALLER, V64) if is_missing(name.rstrip("\\") or name, V64)]


def _scan_openwith() -> list[Issue]:
    out = []
    for app in winutil.reg_subkeys(OPENWITH):
        key = f"{OPENWITH}\\{app}"
        exes = []
        for verb in winutil.reg_subkeys(key + "\\shell"):
            cmd = winutil.reg_get(f"{key}\\shell\\{verb}\\command")
            exe = exe_of(cmd) if isinstance(cmd, str) else None
            if exe:
                exes.append(exe)
        if exes and all(is_missing(e) for e in exes):
            out.append(Issue("openwith", f"{app}: missing {exes[0]}", key, None, "delete_key"))
    return out


def _scan_fonts() -> list[Issue]:
    out = []
    fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for hive, view in (("HKCU", 0), ("HKLM", V64)):
        key = f"{hive}\\{FONTS}"
        for name, data, _t in winutil.reg_values(key, view):
            if not isinstance(data, str) or not data.strip():
                continue
            f = data if re.match(r"^[A-Za-z]:\\", data) else os.path.join(fonts_dir, data)
            if is_missing(f):
                out.append(Issue("fonts", f"{name}: missing {f}", key, name, "delete_value", view))
    return out


SCANNERS: dict[str, Callable[[], list[Issue]]] = {
    "software": _scan_software, "apppaths": _scan_apppaths, "startup": _scan_startup, "muicache": _scan_muicache,
    "shareddlls": _scan_shareddlls, "helpfiles": _scan_help, "sounds": _scan_sounds, "installer": _scan_installer,
    "openwith": _scan_openwith, "fonts": _scan_fonts,
}


def scan(categories: list[str] | None = None, progress: Callable[[str], None] = lambda m: None) -> list[Issue]:
    if not winutil.IS_WINDOWS:
        return []
    out: list[Issue] = []
    seen: set[str] = set()
    for cat in categories or list(SCANNERS):
        progress(f"Scanning {CATEGORIES[cat][0]} ...")
        try:
            found = SCANNERS[cat]()
        except OSError:
            continue
        for i in found:
            if i.key not in seen:
                seen.add(i.key)
                out.append(i)
    return out


# ---- fix / backup / restore ---------------------------------------------------------

def fix(issues: list[Issue], backup_dir: Path) -> tuple[int, list[str], Path | None]:
    """Back up, then fix. Returns (fixed count, errors, backup file)."""
    entries, errors, fixed = [], [], 0
    admin = winutil.is_admin()
    todo = []
    for i in issues:
        if i.needs_admin and not admin:
            errors.append(f"{i.location}: needs administrator")
            continue
        try:
            if i.op == "delete_key":
                data = winutil.reg_dump_view(i.path, i.view)
                entries.append({"kind": "key", "path": i.path, "view": i.view, "value": None, "data": data})
            else:
                with winutil.reg_open_ex(i.path, winreg.KEY_READ, i.view) as k:
                    v, t = winreg.QueryValueEx(k, i.value or "")
                entries.append({"kind": "value", "path": i.path, "view": i.view, "value": i.value,
                                "data": [t, v.hex() if isinstance(v, bytes) else v]})
            todo.append(i)
        except OSError as e:
            errors.append(f"{i.location}: {e.strerror or e}")
    out = None
    if entries:
        backup_dir.mkdir(parents=True, exist_ok=True)
        out = backup_dir / f"registry_issues_{datetime.now():%Y%m%d_%H%M%S}.json"
        out.write_text(json.dumps({"format": "woof-registry-v2", "created": datetime.now().isoformat(timespec="seconds"),
                                   "entries": entries}, indent=1), encoding="utf-8")
    for i in todo:
        try:
            if i.op == "delete_key":
                winutil.reg_delete_tree_view(i.path, i.view)
            elif i.op == "delete_value":
                with winutil.reg_open_ex(i.path, winreg.KEY_SET_VALUE, i.view) as k:
                    winreg.DeleteValue(k, i.value or "")
            else:
                with winutil.reg_open_ex(i.path, winreg.KEY_SET_VALUE, i.view) as k:
                    winreg.SetValueEx(k, i.value or "", 0, winreg.REG_EXPAND_SZ, "")
            fixed += 1
        except OSError as e:
            errors.append(f"{i.location}: {e.strerror or e}")
    return fixed, errors, out


def list_backups(backup_dir: Path) -> list[Path]:
    """Every registry backup Woof Cleaner wrote (cleaner, registry fixes, startup, leftovers), newest first."""
    if not backup_dir.is_dir():
        return []
    files = [p for p in backup_dir.glob("*.json") if p.name.startswith(("registry", "startup", "leftovers", "services",
                                                                        "contextmenu"))]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def restore(backup: Path) -> tuple[int, list[str]]:
    """Write a backup back into the registry. Understands the v2 format and the older {path: dump} files."""
    data = json.loads(backup.read_text(encoding="utf-8"))
    restored, errors = 0, []
    if isinstance(data, dict) and data.get("format") == "woof-registry-v2":
        for e in data.get("entries", []):
            try:
                if e["kind"] == "key":
                    winutil.reg_restore_tree(e["path"], e["data"], e.get("view", 0))
                else:
                    t, v = e["data"]
                    winutil.reg_set(e["path"], e.get("value"), t, v, e.get("view", 0))
                restored += 1
            except (OSError, KeyError, TypeError, ValueError) as ex:
                errors.append(f"{e.get('path')}: {ex}")
        return restored, errors
    if not isinstance(data, dict):
        return 0, ["not a Woof Cleaner registry backup"]
    for k, v in data.items():
        try:
            if isinstance(v, dict) and "values" in v:
                winutil.reg_restore_tree(k, v)
            elif isinstance(v, list) and len(v) == 2 and "|" in k:
                path, name = k.rsplit("|", 1)
                winutil.reg_set(path, name, int(v[0]), v[1])
            else:
                continue
            restored += 1
        except (OSError, TypeError, ValueError) as ex:
            errors.append(f"{k}: {ex}")
    return restored, errors
