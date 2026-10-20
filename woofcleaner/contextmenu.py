"""Right-click (context) menu entries: list, disable/enable, delete (Startup Manager's Context menu tab).

Two kinds of entries exist in the registry under Software\\Classes\\<target>:
* shell extension handlers  `shellex\\ContextMenuHandlers\\<name>` -> a COM CLSID (a DLL). Disabled the
  documented way: the CLSID is added to `Shell Extensions\\Blocked` (HKCU, or HKLM when elevated).
* static verbs              `shell\\<verb>\\command`. Disabled with the `LegacyDisable` value Explorer honours.

On Windows 11 these entries live under "Show more options". Explorer reads handlers once, so a change shows
after Explorer restarts (restart_explorer()). Deleting writes a registry backup first (restorable from the
Registry page).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import winutil

if winutil.IS_WINDOWS:
    import winreg

TARGETS = [("*", "Files"), ("AllFilesystemObjects", "Files and folders"), ("Directory", "Folders"),
           ("Folder", "Folders"), ("Directory\\Background", "Folder background"),
           ("DesktopBackground", "Desktop"), ("Drive", "Drives")]
BLOCKED = r"Software\Microsoft\Windows\CurrentVersion\Shell Extensions\Blocked"
# verbs Windows itself provides (hidden unless "show Windows entries" is on)
_WINDOWS_VERBS = {"find", "cmd", "powershell", "opennewprocess", "opennewtab", "opennewwindow", "pintohome",
                  "runas", "runasuser", "open", "explore", "edit", "print", "printto", "properties", "openas",
                  "updateencryptionsettings", "updateencryptionsettingswork", "wsl", "pintostartscreen"}
_CLSID_RE = re.compile(r"^\{[0-9A-Fa-f-]{36}\}$")


@dataclass
class MenuEntry:
    name: str
    kind: str            # handler | verb
    target: str          # human label ("Files", "Folders", ...)
    key: str             # full key path, e.g. HKCU\Software\Classes\*\shell\VSCode
    clsid: str = ""
    program: str = ""    # DLL (handler) or command line (verb)
    enabled: bool = True
    is_windows: bool = False

    @property
    def needs_admin(self) -> bool:
        return self.key.upper().startswith("HKLM") and self.kind == "verb"

    @property
    def scope(self) -> str:
        return "This user" if self.key.upper().startswith("HKCU") else "All users"


def _blocked() -> set[str]:
    return {n.upper() for hive in ("HKCU", "HKLM") for n, _d, _t in winutil.reg_values(f"{hive}\\{BLOCKED}")}


def _windows_path(p: str) -> bool:
    windir = os.environ.get("WINDIR", r"C:\Windows").lower()
    p = os.path.expandvars(p or "").strip('"').lower()
    return (p.startswith(windir) or r"\windows defender" in p
            or (not os.path.isabs(p) and p.endswith(".dll")))


def _clsid_info(clsid: str) -> tuple[str, str]:
    """(friendly name, DLL path)."""
    for view in (0, winreg.KEY_WOW64_32KEY):
        base = f"HKCR\\CLSID\\{clsid}"
        dll = winutil.reg_get(base + "\\InprocServer32", None, view)
        if dll is not None or winutil.reg_key_exists(base):
            name = winutil.reg_get(base, None, view)
            return (name if isinstance(name, str) else ""), (os.path.expandvars(dll) if isinstance(dll, str) else "")
    return "", ""


def list_entries() -> list[MenuEntry]:
    if not winutil.IS_WINDOWS:
        return []
    blocked = _blocked()
    out: list[MenuEntry] = []
    for hive in ("HKCU", "HKLM"):
        classes = f"{hive}\\Software\\Classes"
        for cls, label in TARGETS:
            hbase = f"{classes}\\{cls}\\shellex\\ContextMenuHandlers"
            for sub in winutil.reg_subkeys(hbase):
                if sub.startswith("-"):
                    continue
                default = winutil.reg_get(f"{hbase}\\{sub}")
                clsid = sub if _CLSID_RE.match(sub) else (default if isinstance(default, str) else "")
                if not _CLSID_RE.match(clsid or ""):
                    continue
                friendly, dll = _clsid_info(clsid)
                name = sub if not _CLSID_RE.match(sub) else (friendly or sub)
                out.append(MenuEntry(name.strip(), "handler", label, f"{hbase}\\{sub}", clsid.upper(), dll,
                                     clsid.upper() not in blocked, _windows_path(dll)))
            vbase = f"{classes}\\{cls}\\shell"
            for verb in winutil.reg_subkeys(vbase):
                key = f"{vbase}\\{verb}"
                vals = {n.lower(): v for n, v, _t in winutil.reg_values(key)}
                cmd = winutil.reg_get(key + "\\command")
                if cmd is None and "explorercommandhandler" not in vals and "subcommands" not in vals:
                    continue
                title = vals.get("muiverb") or vals.get("") or verb
                if isinstance(title, str) and title.startswith("@"):
                    title = verb
                prog = cmd if isinstance(cmd, str) else str(vals.get("explorercommandhandler", ""))
                exe = _clsid_info(prog)[1] if _CLSID_RE.match(prog) else winutil.split_command_line(prog)[0]
                out.append(MenuEntry(str(title).replace("&", "").strip(), "verb", label, key, "", prog,
                                     "legacydisable" not in vals, verb.lower() in _WINDOWS_VERBS or _windows_path(exe)))
    return sorted(out, key=lambda e: (e.target, e.name.lower()))


def set_enabled(e: MenuEntry, enabled: bool) -> None:
    if e.kind == "handler":
        if enabled:
            for hive in ("HKCU", "HKLM"):
                path = f"{hive}\\{BLOCKED}"
                if winutil.reg_value_exists(path, e.clsid) or winutil.reg_value_exists(path, e.clsid.lower()):
                    if hive == "HKLM" and not winutil.is_admin():
                        raise OSError("blocked for all users: restart Woof Cleaner as administrator to unblock")
                    for name, _d, _t in winutil.reg_values(path):
                        if name.upper() == e.clsid:
                            winutil.reg_delete(path, name)
        else:
            hive = "HKLM" if winutil.is_admin() else "HKCU"
            winutil.reg_set(f"{hive}\\{BLOCKED}", e.clsid, winreg.REG_SZ, e.name)
    else:
        if e.needs_admin and not winutil.is_admin():
            raise OSError("this entry is for all users: restart Woof Cleaner as administrator")
        if enabled:
            if winutil.reg_value_exists(e.key, "LegacyDisable"):
                winutil.reg_delete(e.key, "LegacyDisable")
        else:
            winutil.reg_set(e.key, "LegacyDisable", winreg.REG_SZ, "")
    e.enabled = enabled


def delete(entries: list[MenuEntry], backup_dir: Path) -> tuple[int, list[str], Path | None]:
    """Remove entries (registry backup first). Returns (deleted, errors, backup file)."""
    admin = winutil.is_admin()
    backup, errors, done = [], [], 0
    for e in entries:
        if e.key.upper().startswith("HKLM") and not admin:
            errors.append(f"{e.name}: for all users - restart as administrator")
            continue
        try:
            backup.append({"kind": "key", "path": e.key, "view": 0, "value": None, "data": winutil.reg_dump_view(e.key)})
            winutil.reg_delete_tree_view(e.key)
            done += 1
        except OSError as ex:
            errors.append(f"{e.name}: {ex.strerror or ex}")
    out = None
    if backup:
        backup_dir.mkdir(parents=True, exist_ok=True)
        out = backup_dir / f"contextmenu_{datetime.now():%Y%m%d_%H%M%S}.json"
        out.write_text(json.dumps({"format": "woof-registry-v2", "created": datetime.now().isoformat(timespec="seconds"),
                                   "entries": backup}, indent=1), encoding="utf-8")
    return done, errors, out


def restart_explorer() -> None:
    """Explorer loads context-menu handlers once; restart it so changes show."""
    subprocess.run(["taskkill.exe", "/f", "/im", "explorer.exe"], capture_output=True, creationflags=0x08000000)
    subprocess.Popen([os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "explorer.exe")])
