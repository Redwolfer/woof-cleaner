"""Startup manager: Run keys, Startup folders and logon/boot scheduled tasks.

Enable/disable uses the same mechanism as Task Manager's Startup tab:
...\\Explorer\\StartupApproved\\{Run,Run32,StartupFolder} holds a 12-byte value per item;
an even first byte (0x02/0x06) = enabled, odd (0x03/0x07) = disabled + FILETIME of when.
"""
from __future__ import annotations

import os
import struct
import time
from dataclasses import dataclass

from . import winutil

RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUNONCE = r"Software\Microsoft\Windows\CurrentVersion\RunOnce"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"


@dataclass
class StartupItem:
    name: str
    command: str
    source: str           # human label
    kind: str             # registry | folder | task
    location: str         # reg key path / file path / task path
    enabled: bool = True
    approved_key: str = ""   # StartupApproved key (reg path) or "" when not toggleable that way
    reg_view: int = 0
    needs_admin: bool = False


def _filetime_now() -> int:
    return int(time.time() * 10_000_000) + 116444736000000000


def _approved_state(key: str, value: str) -> bool:
    if not winutil.IS_WINDOWS:
        return True
    import winreg
    try:
        with winutil.reg_open_ex(key, winreg.KEY_READ) as k:
            data, _t = winreg.QueryValueEx(k, value)
        return not (isinstance(data, bytes) and data and data[0] & 1)
    except OSError:
        return True


def _registry_items() -> list[StartupItem]:
    import winreg
    items = []
    specs = [
        ("HKCU", RUN, 0, "Run"), ("HKCU", RUNONCE, 0, None),
        ("HKLM", RUN, winreg.KEY_WOW64_64KEY, "Run"), ("HKLM", RUNONCE, winreg.KEY_WOW64_64KEY, None),
        ("HKLM", RUN, winreg.KEY_WOW64_32KEY, "Run32"),
    ]
    for hive, sub, view, approved in specs:
        path = f"{hive}\\{sub}"
        try:
            k = winutil.reg_open_ex(path, winreg.KEY_READ, view)
        except OSError:
            continue
        with k:
            i = 0
            while True:
                try:
                    name, data, _t = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                appr = f"{hive}\\{APPROVED}\\{approved}" if approved else ""
                label = f"{hive} {'RunOnce' if 'RunOnce' in sub else 'Run'}" + (" (32-bit)" if approved == "Run32" else "")
                items.append(StartupItem(
                    name=name, command=str(data), source=label, kind="registry", location=path,
                    enabled=_approved_state(appr, name) if appr else True, approved_key=appr,
                    reg_view=view, needs_admin=hive == "HKLM",
                ))
    return items


def _folder_items() -> list[StartupItem]:
    env = winutil.default_env()
    folders = [
        (os.path.join(env.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup"), "HKCU", "User Startup folder"),
        (os.path.join(env.get("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs\StartUp"), "HKLM", "All-users Startup folder"),
    ]
    items = []
    for folder, hive, label in folders:
        if not os.path.isdir(folder):
            continue
        for e in os.scandir(folder):
            if not e.is_file() or e.name.lower() == "desktop.ini":
                continue
            appr = f"{hive}\\{APPROVED}\\StartupFolder"
            items.append(StartupItem(
                name=os.path.splitext(e.name)[0], command=e.path, source=label, kind="folder", location=e.path,
                enabled=_approved_state(appr, e.name), approved_key=appr, needs_admin=hive == "HKLM",
            ))
    return items


_TASKS_PS = r"""
Get-ScheduledTask | Where-Object {
  $_.TaskPath -notlike '\Microsoft\*' -and ($_.Triggers | Where-Object { $_.CimClass.CimClassName -match 'Logon|Boot' })
} | ForEach-Object {
  [pscustomobject]@{ Name=$_.TaskName; Path=$_.TaskPath; State=[string]$_.State;
    Command=(($_.Actions | ForEach-Object { ($_.Execute + ' ' + $_.Arguments).Trim() }) -join '; ') }
} | ConvertTo-Json -Compress
"""


def _task_items() -> list[StartupItem]:
    try:
        rows = winutil.ps_json(_TASKS_PS, timeout=120)
    except Exception:
        return []
    return [
        StartupItem(name=r["Name"], command=r.get("Command") or "", source="Scheduled task (logon/boot)",
                    kind="task", location=(r["Path"] or "\\") + r["Name"],
                    enabled=r.get("State") != "Disabled", needs_admin=True)
        for r in rows
    ]


def list_items(include_tasks: bool = True) -> list[StartupItem]:
    if not winutil.IS_WINDOWS:
        return []
    items = _registry_items() + _folder_items()
    if include_tasks:
        items += _task_items()
    return items


def _value_name(item: StartupItem) -> str:
    return os.path.basename(item.location) if item.kind == "folder" else item.name


def set_enabled(item: StartupItem, enabled: bool) -> None:
    import winreg
    if item.kind == "task":
        verb = "/enable" if enabled else "/disable"
        rc = winutil.shell_execute("schtasks.exe", f'/change /tn "{item.location}" {verb}', show=0)
        if rc:
            raise OSError(f"schtasks exited with {rc} (needs administrator?)")
    elif item.approved_key:
        data = (b"\x02" + b"\x00" * 11) if enabled else (b"\x03\x00\x00\x00" + struct.pack("<Q", _filetime_now()))
        hive, sub = winutil._split_reg(item.approved_key)
        with winreg.CreateKeyEx(hive, sub, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, _value_name(item), 0, winreg.REG_BINARY, data)
    else:
        raise OSError("this entry (RunOnce) can only be deleted, not disabled")
    item.enabled = enabled


def delete(item: StartupItem, backup: dict) -> None:
    import winreg
    if item.kind == "registry":
        with winutil.reg_open_ex(item.location, winreg.KEY_READ, item.reg_view) as k:
            data, t = winreg.QueryValueEx(k, item.name)
        backup[f"{item.location}|{item.name}"] = [t, data]
        with winutil.reg_open_ex(item.location, winreg.KEY_SET_VALUE, item.reg_view) as k:
            winreg.DeleteValue(k, item.name)
    elif item.kind == "folder":
        winutil.send_to_recycle_bin([item.location])
    else:
        rc = winutil.shell_execute("schtasks.exe", f'/delete /tn "{item.location}" /f', show=0)
        if rc:
            raise OSError(f"schtasks exited with {rc} (needs administrator?)")
    if item.approved_key:
        try:
            with winutil.reg_open_ex(item.approved_key, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, _value_name(item))
        except OSError:
            pass
