"""Scheduled cleaning through Windows Task Scheduler (plus "start elevated without a UAC prompt").

CCleaner 7 offers daily / weekly / every-2-weeks / at-startup schedules and runs a missed schedule the next
time the PC is on. The same is done here:

* daily, weekly, biweekly -> a per-user scheduled task registered from XML so that StartWhenAvailable
  ("run as soon as possible after a missed start") and battery settings can be set; schtasks' own switches
  can't set those.
* logon -> a value in HKCU\\...\\Run (a logon-triggered task needs administrator rights to create).

Every schedule runs `auto-clean`, which cleans the rules ticked in Custom Clean (settings "clean_selection",
or the default rules) without asking, and appends a line to settings "autoclean_history".
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

from . import paths, settings, winutil

TASK_PREFIX = "Woof Cleaner Auto Clean"
ELEVATED_TASK = "Woof Cleaner Elevated Launch"
RUN_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "WoofCleanerAutoClean"
FREQUENCIES = {"daily": "Daily", "weekly": "Weekly", "biweekly": "Every 2 weeks", "logon": "At every sign-in"}
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
ROOT = paths.RESOURCES


@dataclass
class Schedule:
    id: str
    frequency: str           # daily | weekly | biweekly | logon
    day: str = "Monday"      # weekly / biweekly
    time: str = "10:00"      # HH:MM, not used for logon
    elevated: bool = False
    enabled: bool = True
    # status (filled by list_schedules)
    next_run: str = ""
    last_run: str = ""
    last_result: str = ""

    @property
    def task_name(self) -> str:
        return f"{TASK_PREFIX} {self.id}"

    @property
    def description(self) -> str:
        if self.frequency == "logon":
            return "At every sign-in (1 minute after)"
        when = f"at {self.time}"
        if self.frequency == "daily":
            return f"Every day {when}"
        if self.frequency == "weekly":
            return f"Every {self.day} {when}"
        return f"Every 2 weeks on {self.day} {when}"

    def to_json(self) -> dict:
        return {"id": self.id, "frequency": self.frequency, "day": self.day, "time": self.time,
                "elevated": self.elevated, "enabled": self.enabled}


# ---- how to start ourselves -----------------------------------------------------------

def launch_command(*args: str) -> tuple[str, str, str]:
    """(program, arguments, working dir) that start this copy of Woof Cleaner with `args`, without a console."""
    if paths.FROZEN:
        exe = sys.executable
        if os.path.basename(exe).lower() == "woof.exe":       # the console build: prefer the windowed sibling
            gui = os.path.join(os.path.dirname(exe), "WoofCleaner.exe")
            exe = gui if os.path.exists(gui) else exe
        return exe, " ".join(args), str(paths.EXE_DIR)
    py = sys.executable
    if py.lower().endswith("python.exe") and os.path.exists(py[:-10] + "pythonw.exe"):
        py = py[:-10] + "pythonw.exe"
    script = os.path.join(str(ROOT), "woof_gui.py")
    return py, f'"{script}" ' + " ".join(args), str(ROOT)


def _quote(exe: str) -> str:
    return f'"{exe}"' if " " in exe and not exe.startswith('"') else exe


# ---- task XML ------------------------------------------------------------------------------

def _user() -> str:
    dom, user = os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", "")
    return f"{dom}\\{user}" if dom else user


def task_xml(trigger_xml: str, exe: str, args: str, cwd: str, elevated: bool, description: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Author>Woof Cleaner</Author><Description>{escape(description)}</Description></RegistrationInfo>
  <Triggers>{trigger_xml}</Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(_user())}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>{"HighestAvailable" if elevated else "LeastPrivilege"}</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(exe)}</Command>
      <Arguments>{escape(args)}</Arguments>
      <WorkingDirectory>{escape(cwd)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def calendar_trigger(s: Schedule, now: datetime | None = None) -> str:
    now = now or datetime.now()
    hh, mm = (int(x) for x in s.time.split(":"))
    start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if s.frequency in ("weekly", "biweekly"):
        start += timedelta(days=(DAYS.index(s.day) - start.weekday()) % 7)
        body = (f"<ScheduleByWeek><DaysOfWeek><{s.day} /></DaysOfWeek>"
                f"<WeeksInterval>{2 if s.frequency == 'biweekly' else 1}</WeeksInterval></ScheduleByWeek>")
    else:
        body = "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>"
    return (f"<CalendarTrigger><StartBoundary>{start:%Y-%m-%dT%H:%M:%S}</StartBoundary>"
            f"<Enabled>true</Enabled>{body}</CalendarTrigger>")


def _schtasks(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks.exe", *args], capture_output=True, text=True, timeout=60,
                          creationflags=0x08000000)


def _register(name: str, xml: str) -> None:
    fd, f = tempfile.mkstemp(suffix=".xml")
    os.close(fd)
    try:
        with open(f, "w", encoding="utf-16") as fh:
            fh.write(xml)
        r = _schtasks("/Create", "/TN", name, "/XML", f, "/F")
        if r.returncode:
            raise OSError((r.stderr or r.stdout).strip() or f"schtasks exited with {r.returncode}")
    finally:
        os.remove(f)


def task_exists(name: str) -> bool:
    return winutil.IS_WINDOWS and _schtasks("/Query", "/TN", name).returncode == 0


# ---- schedules -------------------------------------------------------------------------------

def _stored() -> list[Schedule]:
    out = []
    for d in settings.get("schedules", []):
        try:
            out.append(Schedule(**{k: d[k] for k in ("id", "frequency", "day", "time", "elevated", "enabled") if k in d}))
        except TypeError:
            continue
    return out


def _store(items: list[Schedule]) -> None:
    settings.save(schedules=[s.to_json() for s in items])


_STATUS_PS = r"""
$out = foreach ($n in @({names})) {
  $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
  if ($t) {
    $i = $t | Get-ScheduledTaskInfo
    [pscustomobject]@{ Name=$n; State=[string]$t.State;
      Next=$(if ($i.NextRunTime) { $i.NextRunTime.ToString('yyyy-MM-dd HH:mm') } else { '' });
      Last=$(if ($i.LastRunTime -and $i.LastRunTime.Year -gt 2000) { $i.LastRunTime.ToString('yyyy-MM-dd HH:mm') } else { '' });
      Result=[int64]$i.LastTaskResult }
  }
}
ConvertTo-Json -Compress -InputObject @($out)
"""


def list_schedules(with_status: bool = True) -> list[Schedule]:
    items = _stored()
    if not with_status or not winutil.IS_WINDOWS:
        return items
    tasks = [s for s in items if s.frequency != "logon"]
    status = {}
    if tasks:
        names = ",".join("'" + s.task_name.replace("'", "''") + "'" for s in tasks)
        try:
            status = {r["Name"]: r for r in winutil.ps_json(_STATUS_PS.replace("{names}", names), timeout=60)}
        except Exception:
            status = {}
    history = settings.get("autoclean_history", [])
    for s in items:
        if s.frequency == "logon":
            s.enabled = winutil.reg_value_exists(RUN_KEY, RUN_VALUE)
            last = next((h for h in reversed(history) if h.get("trigger") == "logon"), None)
            s.next_run = "next sign-in" if s.enabled else ""
            s.last_run = last["time"] if last else ""
            s.last_result = "OK" if last else ""
            continue
        st = status.get(s.task_name)
        if not st:
            s.last_result = "task missing - save it again"
            continue
        s.enabled = st.get("State") != "Disabled"
        s.next_run = st.get("Next") or ""
        s.last_run = st.get("Last") or ""
        code = int(st.get("Result") or 0)
        s.last_result = "" if not s.last_run else ("OK" if code == 0 else
                                                   "running" if code == 0x41301 else f"error 0x{code & 0xFFFFFFFF:X}")
    return items


def add_schedule(frequency: str, day: str = "Monday", time: str = "10:00", elevated: bool = False) -> Schedule:
    if frequency not in FREQUENCIES:
        raise ValueError(f"unknown frequency {frequency}")
    if day not in DAYS:
        raise ValueError(f"unknown day {day}")
    datetime.strptime(time, "%H:%M")
    if elevated and not winutil.is_admin():
        raise OSError("run Woof Cleaner as administrator to create a schedule with administrator rights")
    items = _stored()
    if frequency == "logon" and any(s.frequency == "logon" for s in items):
        raise ValueError("there is already an at-sign-in schedule")
    s = Schedule(uuid.uuid4().hex[:6], frequency, day, time, elevated)
    _apply(s)
    _store(items + [s])
    return s


def _apply(s: Schedule) -> None:
    if s.frequency == "logon":
        exe, args, _cwd = launch_command("auto-clean", "--trigger", "logon", "--delay", "60")
        winutil.reg_set(RUN_KEY, RUN_VALUE, 1, f"{_quote(exe)} {args}")
        return
    exe, args, cwd = launch_command("auto-clean", "--trigger", s.id)
    _register(s.task_name, task_xml(calendar_trigger(s), exe, args, cwd, s.elevated,
                                    f"Woof Cleaner scheduled clean: {s.description}"))


def set_enabled(schedule_id: str, enabled: bool) -> None:
    items = _stored()
    s = next(x for x in items if x.id == schedule_id)
    if s.frequency == "logon":
        if enabled:
            _apply(s)
        elif winutil.reg_value_exists(RUN_KEY, RUN_VALUE):
            winutil.reg_delete(RUN_KEY, RUN_VALUE)
    else:
        r = _schtasks("/Change", "/TN", s.task_name, "/ENABLE" if enabled else "/DISABLE")
        if r.returncode:
            raise OSError((r.stderr or r.stdout).strip())
    s.enabled = enabled
    _store(items)


def remove_schedule(schedule_id: str) -> None:
    items = _stored()
    s = next(x for x in items if x.id == schedule_id)
    if s.frequency == "logon":
        if winutil.reg_value_exists(RUN_KEY, RUN_VALUE):
            winutil.reg_delete(RUN_KEY, RUN_VALUE)
    elif task_exists(s.task_name):
        r = _schtasks("/Delete", "/TN", s.task_name, "/F")
        if r.returncode:
            raise OSError((r.stderr or r.stdout).strip())
    _store([x for x in items if x.id != schedule_id])


def remove_all() -> list[str]:
    """Remove every schedule and the elevated-launch task (used by the uninstaller). Returns errors."""
    errors = []
    for s in _stored():
        try:
            remove_schedule(s.id)
        except (OSError, StopIteration) as e:
            errors.append(f"{s.id}: {e}")
    if winutil.IS_WINDOWS:
        r = _schtasks("/Query", "/FO", "CSV", "/NH")
        for line in r.stdout.splitlines():
            name = line.split('","')[0].strip('"').lstrip("\\")
            if name.startswith((TASK_PREFIX, ELEVATED_TASK)):
                d = _schtasks("/Delete", "/TN", name, "/F")
                if d.returncode:
                    errors.append(f"{name}: {(d.stderr or d.stdout).strip()}")
        if winutil.reg_value_exists(RUN_KEY, RUN_VALUE):
            winutil.reg_delete(RUN_KEY, RUN_VALUE)
    settings.save(schedules=[], auto_elevate=False)
    return errors


def run_now(schedule_id: str) -> None:
    s = next(x for x in _stored() if x.id == schedule_id)
    if s.frequency == "logon":
        exe, args, cwd = launch_command("auto-clean", "--trigger", "manual")
        subprocess.Popen(f"{_quote(exe)} {args}", cwd=cwd, creationflags=0x08000000)
        return
    r = _schtasks("/Run", "/TN", s.task_name)
    if r.returncode:
        raise OSError((r.stderr or r.stdout).strip())


# ---- start elevated without UAC ----------------------------------------------------------------

def elevated_launch_enabled() -> bool:
    return bool(settings.get("auto_elevate")) and task_exists(ELEVATED_TASK)


def set_elevated_launch(enabled: bool) -> None:
    """Create/remove an on-demand task with highest privileges that opens the GUI. Needs administrator."""
    if enabled:
        if not winutil.is_admin():
            raise OSError("restart Woof Cleaner as administrator first (creating the task needs administrator rights)")
        exe, args, cwd = launch_command("gui", "--elevated-launch")
        _register(ELEVATED_TASK, task_xml("", exe, args, cwd, True, "Starts Woof Cleaner with administrator rights "
                                          "without a UAC prompt (created from Woof Cleaner Settings)."))
    elif task_exists(ELEVATED_TASK):
        r = _schtasks("/Delete", "/TN", ELEVATED_TASK, "/F")
        if r.returncode:
            raise OSError((r.stderr or r.stdout).strip() or "could not delete the task (administrator needed?)")
    settings.save(auto_elevate=enabled)


def start_elevated() -> bool:
    """Run the elevated-launch task. True when the elevated copy was started."""
    return winutil.IS_WINDOWS and _schtasks("/Run", "/TN", ELEVATED_TASK).returncode == 0


# ---- history ----------------------------------------------------------------------------------

def record_run(trigger: str, freed: int, files: int, records: int, rules: int, errors: int) -> None:
    hist = settings.get("autoclean_history", [])
    hist.append({"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "trigger": trigger, "freed": freed,
                 "files": files, "records": records, "rules": rules, "errors": errors})
    settings.save(autoclean_history=hist[-100:])
