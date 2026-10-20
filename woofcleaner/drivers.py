"""Driver inventory + driver updates from Windows Update (Microsoft-signed drivers only)."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass

from . import winutil

_INVENTORY_PS = r"""
Get-CimInstance Win32_PnPSignedDriver | Where-Object { $_.DeviceName } | ForEach-Object {
  [pscustomobject]@{ Device=$_.DeviceName; Class=[string]$_.DeviceClass; Version=[string]$_.DriverVersion;
    Date=$(if ($_.DriverDate) { $_.DriverDate.ToString('yyyy-MM-dd') } else { '' });
    Provider=[string]$_.DriverProviderName; Inf=[string]$_.InfName }
} | ConvertTo-Json -Compress
"""

_PROBLEMS_PS = r"""
Get-CimInstance Win32_PnPEntity | Where-Object { $_.ConfigManagerErrorCode -ne 0 } | ForEach-Object {
  [pscustomobject]@{ Device=$(if ($_.Name) { $_.Name } else { $_.PNPDeviceID }); Code=[int]$_.ConfigManagerErrorCode;
    Id=[string]$_.PNPDeviceID }
} | ConvertTo-Json -Compress
"""

_SEARCH_PS = r"""
$s = New-Object -ComObject Microsoft.Update.Session
$s.ClientApplicationID = 'Woof Cleaner'
$r = $s.CreateUpdateSearcher().Search("IsInstalled=0 and Type='Driver' and IsHidden=0")
@($r.Updates | ForEach-Object {
  [pscustomobject]@{ Title=$_.Title; UpdateId=$_.Identity.UpdateID; Class=[string]$_.DriverClass;
    Manufacturer=[string]$_.DriverManufacturer; Model=[string]$_.DriverModel;
    Date=$(if ($_.DriverVerDate) { ([datetime]$_.DriverVerDate).ToString('yyyy-MM-dd') } else { '' });
    SizeMB=[math]::Round($_.MaxDownloadSize / 1MB, 1) }
}) | ConvertTo-Json -Compress
"""

# Runs elevated. Installs the selected update IDs and writes a JSON report to $out.
_INSTALL_PS = r"""
param([string]$ids, [string]$out)
$ErrorActionPreference = 'Stop'
$report = @()
try {
  $s = New-Object -ComObject Microsoft.Update.Session
  $s.ClientApplicationID = 'Woof Cleaner'
  # Safety net first. Windows allows one restore point per 24 h and only when System Protection is on;
  # either way we report what happened instead of silently skipping it.
  $rp = 'created'
  try {
    Checkpoint-Computer -Description 'Woof Cleaner driver update' -RestorePointType MODIFY_SETTINGS -ErrorAction Stop -WarningVariable rpw 3>$null
    if ($rpw) { $rp = 'skipped: ' + [string]$rpw[0] }
  } catch { $rp = 'not created: ' + $_.Exception.Message }
  $report += [pscustomobject]@{ Title='__restorepoint__'; Result=0; Message=$rp }
  $want = $ids -split ','
  $res = $s.CreateUpdateSearcher().Search("IsInstalled=0 and Type='Driver'")
  $col = New-Object -ComObject Microsoft.Update.UpdateColl
  foreach ($u in $res.Updates) { if ($want -contains $u.Identity.UpdateID) { if (-not $u.EulaAccepted) { $u.AcceptEula() }; [void]$col.Add($u) } }
  if ($col.Count -eq 0) { throw 'none of the selected updates are still applicable' }
  $d = $s.CreateUpdateDownloader(); $d.Updates = $col; [void]$d.Download()
  $i = $s.CreateUpdateInstaller(); $i.Updates = $col; $r = $i.Install()
  for ($n = 0; $n -lt $col.Count; $n++) {
    $report += [pscustomobject]@{ Title=$col.Item($n).Title; Result=[int]$r.GetUpdateResult($n).ResultCode }
  }
  $report += [pscustomobject]@{ Title='__summary__'; Result=[int]$r.ResultCode; Reboot=[bool]$r.RebootRequired }
} catch {
  $report += [pscustomobject]@{ Title='__error__'; Result=-1; Message=$_.Exception.Message }
}
$report | ConvertTo-Json -Compress | Set-Content -Path $out -Encoding UTF8
"""

RESULT_CODES = {0: "not started", 1: "in progress", 2: "installed", 3: "installed with errors", 4: "failed", 5: "aborted"}

PROBLEM_CODES = {1: "not configured", 3: "driver corrupted", 10: "cannot start", 18: "reinstall drivers",
                 22: "disabled", 24: "not present", 28: "no driver installed", 31: "not working properly",
                 43: "stopped (reported problems)", 45: "not connected"}


@dataclass
class Driver:
    device: str
    cls: str
    version: str
    date: str
    provider: str
    inf: str


@dataclass
class DriverUpdate:
    title: str
    update_id: str
    cls: str
    manufacturer: str
    model: str
    date: str
    size_mb: float


@dataclass
class ProblemDevice:
    device: str
    code: int
    pnp_id: str

    @property
    def problem(self) -> str:
        return PROBLEM_CODES.get(self.code, f"error code {self.code}")


def installed_drivers() -> list[Driver]:
    rows = winutil.ps_json(_INVENTORY_PS, timeout=120)
    return sorted((Driver(r["Device"], r["Class"], r["Version"], r["Date"], r["Provider"], r["Inf"]) for r in rows),
                  key=lambda d: (d.cls.lower(), d.device.lower()))


def problem_devices() -> list[ProblemDevice]:
    return [ProblemDevice(r["Device"], r["Code"], r["Id"]) for r in winutil.ps_json(_PROBLEMS_PS, timeout=120)]


def search_updates() -> list[DriverUpdate]:
    """Ask Windows Update for applicable driver updates (no admin needed; ~30-120 s)."""
    rows = winutil.ps_json(_SEARCH_PS, timeout=600)
    return [DriverUpdate(r["Title"], r["UpdateId"], r["Class"], r["Manufacturer"], r["Model"], r["Date"],
                         float(r.get("SizeMB") or 0)) for r in rows]


def install_updates(update_ids: list[str]) -> list[dict]:
    """Download + install via Windows Update in an elevated PowerShell (one UAC prompt)."""
    tmp = tempfile.mkdtemp(prefix="woof_drv_")
    script = os.path.join(tmp, "install.ps1")
    out = os.path.join(tmp, "result.json")
    with open(script, "w", encoding="utf-8-sig") as f:
        f.write(_INSTALL_PS)
    args = (f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{script}" '
            f'-ids "{",".join(update_ids)}" -out "{out}"')
    winutil.shell_execute("powershell.exe", args, verb="runas", wait=True, show=0)
    if not os.path.exists(out):
        raise RuntimeError("the elevated installer produced no result (cancelled?)")
    with open(out, encoding="utf-8-sig") as f:
        data = json.load(f)
    return data if isinstance(data, list) else [data]


def open_device_manager() -> None:
    winutil.shell_execute("devmgmt.msc", wait=False)
