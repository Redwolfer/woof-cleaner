"""Installed-program inventory, uninstall launcher and leftover scanner.

Programs come from the same place Windows "Apps & features" reads:
HKLM (64- and 32-bit views) and HKCU ...\\CurrentVersion\\Uninstall.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from . import winutil

UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"


@dataclass
class Program:
    name: str
    version: str = ""
    publisher: str = ""
    install_date: str = ""
    size_kb: int = 0
    install_location: str = ""
    uninstall_string: str = ""
    quiet_uninstall_string: str = ""
    product_code: str = ""   # MSI GUID when WindowsInstaller=1
    scope: str = "Machine"   # Machine | User
    arch: str = "x64"
    reg_path: str = ""       # e.g. HKLM\Software\...\Uninstall\{GUID}
    reg_view: int = 0        # winreg KEY_WOW64_* flag needed to reopen reg_path

    @property
    def is_msi(self) -> bool:
        return bool(self.product_code)

    @property
    def can_uninstall(self) -> bool:
        return bool(self.uninstall_string or self.product_code)


def _val(k, name, default=""):
    import winreg
    try:
        return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return default


def list_programs(include_system: bool = False) -> list[Program]:
    if not winutil.IS_WINDOWS:
        return []
    import winreg
    sources = [
        (winreg.HKEY_LOCAL_MACHINE, "HKLM", winreg.KEY_WOW64_64KEY, "Machine", "x64"),
        (winreg.HKEY_LOCAL_MACHINE, "HKLM", winreg.KEY_WOW64_32KEY, "Machine", "x86"),
        (winreg.HKEY_CURRENT_USER, "HKCU", 0, "User", ""),
    ]
    seen: set[tuple[str, str]] = set()
    out: list[Program] = []
    for hive, hname, view, scope, arch in sources:
        try:
            root = winreg.OpenKey(hive, UNINSTALL, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    k = winreg.OpenKey(root, sub)
                except OSError:
                    continue
                with k:
                    name = str(_val(k, "DisplayName")).strip()
                    if not name:
                        continue
                    if not include_system:
                        if _val(k, "SystemComponent", 0) == 1 or _val(k, "ParentKeyName"):
                            continue
                        if str(_val(k, "ReleaseType")) in ("Update", "Hotfix", "Security Update"):
                            continue
                    p = Program(
                        name=name,
                        version=str(_val(k, "DisplayVersion")),
                        publisher=str(_val(k, "Publisher")),
                        install_date=_fmt_date(str(_val(k, "InstallDate"))),
                        size_kb=int(_val(k, "EstimatedSize", 0) or 0),
                        install_location=str(_val(k, "InstallLocation")).strip().strip('"'),
                        uninstall_string=str(_val(k, "UninstallString")).strip(),
                        quiet_uninstall_string=str(_val(k, "QuietUninstallString")).strip(),
                        product_code=sub if (_val(k, "WindowsInstaller", 0) == 1 and sub.startswith("{")) else "",
                        scope=scope,
                        arch=arch,
                        reg_path=f"{hname}\\{UNINSTALL}\\{sub}",
                        reg_view=view,
                    )
                key = (p.name.lower(), p.version)
                if key in seen:
                    continue
                seen.add(key)
                out.append(p)
    out.sort(key=lambda p: p.name.lower())
    return out


def _fmt_date(d: str) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if re.fullmatch(r"\d{8}", d) else ""


def uninstall_command(p: Program, quiet: bool = False) -> tuple[str, str]:
    """(exe, args) to launch. MSI products go through msiexec /x."""
    if p.is_msi:
        return "msiexec.exe", f"/x {p.product_code}" + (" /qb" if quiet else "")
    cmd = p.quiet_uninstall_string if (quiet and p.quiet_uninstall_string) else p.uninstall_string
    exe, args = winutil.split_command_line(cmd)
    # Some entries use "MsiExec.exe /I{GUID}" which would *repair*; force uninstall.
    if os.path.basename(exe).lower() == "msiexec.exe":
        args = re.sub(r"(?i)/i\s*(\{[0-9a-f-]+\})", r"/x \1", args)
    return exe, args


def run_uninstaller(p: Program, quiet: bool = False) -> int | None:
    """Launch the vendor's uninstaller and wait. UAC is prompted when needed."""
    if not p.can_uninstall:
        raise ValueError(f"{p.name} has no uninstall command")
    exe, args = uninstall_command(p, quiet)
    return winutil.shell_execute(exe, args, wait=True)


def is_still_installed(p: Program) -> bool:
    import winreg
    try:
        winutil.reg_open_ex(p.reg_path, winreg.KEY_READ, p.reg_view).Close()
        return True
    except OSError:
        return False


# ---- leftovers ---------------------------------------------------------------

_NOISE = re.compile(r"\s*(\(?(x64|x86|64-bit|32-bit|amd64|win64)\)?|v?\d+(\.\d+)+.*|\(.*?\))\s*$", re.I)
_PROTECTED = {"microsoft", "windows", "common files", "windowsapps", "packages", "temp", "programs",
              "google", "mozilla", "intel", "nvidia", "amd", "adobe", "apple"}


def base_name(name: str) -> str:
    prev = None
    n = name.strip()
    while prev != n:
        prev, n = n, _NOISE.sub("", n).strip(" -_")
    return n


@dataclass
class Leftover:
    kind: str   # folder | registry
    path: str
    size: int = 0
    reason: str = ""


def _dir_size(path: str) -> int:
    total = 0
    for dp, _dn, fns in os.walk(path):
        for f in fns:
            try:
                total += os.lstat(os.path.join(dp, f)).st_size
            except OSError:
                pass
    return total


def find_leftovers(p: Program) -> list[Leftover]:
    """Conservative leftover scan: exact (normalised) name matches only, never shared vendor roots."""
    if is_still_installed(p):
        return []  # only meaningful after the vendor uninstaller has run
    env = winutil.default_env()
    found: dict[str, Leftover] = {}
    if p.install_location and os.path.isdir(p.install_location) and len(os.path.normpath(p.install_location).split(os.sep)) >= 3:
        found[p.install_location.lower()] = Leftover("folder", p.install_location, reason="InstallLocation")
    names = {n.lower() for n in (base_name(p.name), p.name) if n and n.lower() not in _PROTECTED and len(n) >= 3}
    pub = base_name(p.publisher.split(",")[0]).lower() if p.publisher else ""
    roots = [env.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA")]
    for root in filter(os.path.isdir, roots):
        candidates = [root]
        if pub and pub not in _PROTECTED and os.path.isdir(os.path.join(root, pub)):
            candidates.append(os.path.join(root, pub))
        for base in candidates:
            try:
                entries = list(os.scandir(base))
            except OSError:
                continue
            for e in entries:
                if e.is_dir(follow_symlinks=False) and e.name.lower() in names:
                    found.setdefault(e.path.lower(), Leftover("folder", e.path, reason="name match"))
    for lo in found.values():
        lo.size = _dir_size(lo.path)
    if winutil.IS_WINDOWS:
        parents = ["HKCU\\Software"]
        if p.publisher and p.publisher.lower() not in _PROTECTED:
            parents.append(f"HKCU\\Software\\{p.publisher}")
        for n in names:
            for parent in parents:
                path = f"{parent}\\{n}"
                if winutil.reg_key_exists(path):
                    found.setdefault(path.lower(), Leftover("registry", path, reason="name match"))
    return list(found.values())


def remove_leftovers(items: list[Leftover], backup: dict) -> list[str]:
    """Folders go to the Recycle Bin; registry keys are backed up then deleted. Returns error strings."""
    errors = []
    folders = [i.path for i in items if i.kind == "folder"]
    try:
        winutil.send_to_recycle_bin(folders)
    except OSError as e:
        errors.append(str(e))
    for i in items:
        if i.kind != "registry":
            continue
        try:
            h, sub = winutil._split_reg(i.path)
            backup[i.path] = winutil.reg_dump(h, sub)
            winutil.reg_delete(i.path, None)
        except OSError as e:
            errors.append(f"{i.path}: {e}")
    return errors
