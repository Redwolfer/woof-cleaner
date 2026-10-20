"""Windows services: list them, change the start type, start/stop (CCleaner Startup Manager's Services tab).

Changes go through `sc.exe` in one elevated PowerShell run (a single UAC prompt for a batch). The previous
start types are written to backups\\services_*.json first.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import winutil

START_TYPES = {"auto": "Automatic", "delayed-auto": "Automatic (delayed)", "demand": "Manual", "disabled": "Disabled"}

_LIST_PS = r"""
Get-CimInstance Win32_Service | ForEach-Object {
  [pscustomobject]@{ N=$_.Name; D=[string]$_.DisplayName; S=[string]$_.State; M=[string]$_.StartMode;
    Dl=[bool]$_.DelayedAutoStart; P=[string]$_.PathName; Ds=[string]$_.Description }
} | ConvertTo-Json -Compress
"""

# Runs (elevated when needed): one sc.exe call per line of $jobs ("name<TAB>verb<TAB>arg"), report to $out.
_APPLY_PS = r"""
param([string]$jobs, [string]$out)
$r = foreach ($line in (Get-Content -LiteralPath $jobs -Encoding UTF8)) {
  if (-not $line) { continue }
  $n, $verb, $arg = $line -split "`t"
  if ($verb -eq 'config') { $o = & sc.exe config $n start= $arg 2>&1 } else { $o = & sc.exe $verb $n 2>&1 }
  [pscustomobject]@{ Name=$n; Code=$LASTEXITCODE; Out=(($o | Out-String).Trim()) }
}
ConvertTo-Json -Compress -InputObject @($r) | Set-Content -LiteralPath $out -Encoding UTF8
"""


@dataclass
class Service:
    name: str
    display: str
    state: str          # Running | Stopped | ...
    start_mode: str     # Auto | Manual | Disabled | Boot | System
    delayed: bool
    path: str
    description: str

    @property
    def start_label(self) -> str:
        if self.start_mode == "Auto":
            return "Automatic (delayed)" if self.delayed else "Automatic"
        return {"Manual": "Manual", "Disabled": "Disabled"}.get(self.start_mode, self.start_mode)

    @property
    def is_microsoft(self) -> bool:
        """Windows' own services (system folder) and other Microsoft ones: hidden by default, like msconfig."""
        p = self.path.lower().strip('"')
        windir = os.environ.get("WINDIR", r"C:\Windows").lower()
        return p.startswith(windir) or "\\microsoft" in p or "\\windows defender" in p or not p


def list_services() -> list[Service]:
    if not winutil.IS_WINDOWS:
        return []
    rows = winutil.ps_json(_LIST_PS, timeout=120)
    return sorted((Service(r["N"], r["D"] or r["N"], r["S"], r["M"], bool(r.get("Dl")), r["P"], r["Ds"]) for r in rows),
                  key=lambda s: s.display.lower())


def _run(jobs: list[tuple[str, str, str]]) -> list[dict]:
    tmp = tempfile.mkdtemp(prefix="woof_svc_")
    script, jobfile, out = (os.path.join(tmp, n) for n in ("apply.ps1", "jobs.txt", "out.json"))
    with open(script, "w", encoding="utf-8-sig") as f:
        f.write(_APPLY_PS)
    with open(jobfile, "w", encoding="utf-8") as f:
        f.write("\n".join("\t".join(j) for j in jobs))
    if winutil.is_admin():
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
                        "-jobs", jobfile, "-out", out], capture_output=True, timeout=600, creationflags=0x08000000)
    else:
        args = f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{script}" -jobs "{jobfile}" -out "{out}"'
        winutil.shell_execute("powershell.exe", args, verb="runas", wait=True, show=0)
    if not os.path.exists(out):
        raise RuntimeError("the change was not applied (UAC prompt cancelled?)")
    with open(out, encoding="utf-8-sig") as f:
        data = json.load(f)
    return data if isinstance(data, list) else [data]


def _report(rows: list[dict]) -> list[str]:
    return [f"{r['Name']}: {r.get('Out') or 'exit ' + str(r['Code'])}" for r in rows if r.get("Code")]


def set_start_type(items: list[Service], start: str, backup_dir: Path) -> list[str]:
    """start: auto | delayed-auto | demand | disabled. Returns error lines."""
    if start not in START_TYPES:
        raise ValueError(start)
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / f"services_{datetime.now():%Y%m%d_%H%M%S}.json").write_text(json.dumps(
        {"format": "woof-services-v1", "services": {s.name: {"start": s.start_mode, "delayed": s.delayed,
                                                             "display": s.display} for s in items}}, indent=1),
        encoding="utf-8")
    return _report(_run([(s.name, "config", start) for s in items]))


def control(items: list[Service], verb: str) -> list[str]:
    """verb: start | stop."""
    if verb not in ("start", "stop"):
        raise ValueError(verb)
    return _report(_run([(s.name, verb, "") for s in items]))
