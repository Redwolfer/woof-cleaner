# How Woof Cleaner works

Woof Cleaner is pure Python (standard library only). The cleaning knowledge lives in a data file,
`data/rules.ini`; the code is a small engine that reads the rules and applies them. The other tools
(registry cleaner, startup manager, updaters, schedules) are separate modules that use Windows' own
mechanisms.

```
 woofcleaner/gui/*        Tk window: sidebar of pages, light/dark theme
 woofcleaner/cli.py       the same tools on the command line (woof.exe)
        │
        ▼
 engine.py  ── rules.py ── data/rules.ini      what is junk, as declarative rules
   ├─ browserdb.py        browser databases, row by row
   └─ winutil.py          Windows helpers (registry, Recycle Bin, DNS, event logs, ...)
 regscan.py               registry cleaner
 startup.py / services.py / contextmenu.py      Startup Manager
 updater.py (winget) / drivers.py (Windows Update)
 uninstaller.py / duplicates.py
 scheduler.py             scheduled cleaning (Task Scheduler)
 settings.py              settings.json in %LOCALAPPDATA%\WoofCleaner
```

## 1. Cleaning rules

`data/rules.ini` is a plain INI file: one `[Rule Vars]` section, then one section per rule. A `rules.ini`
next to the exe overrides the bundled one, so rules can be added without rebuilding.

| Key | Meaning |
|---|---|
| `ID`, `Group`, `Default` | stable id, sidebar group, ticked by default or not |
| `FileKeyN=<dir>\|<patterns>\|<flags>` | files to delete. Patterns are `;`-separated. Flags: `RECURSE` (subfolders), `REMOVESELF` (the folder too) |
| `RegKeyN=<key>[\|<value>]` | registry key or value to delete (HKCU only), backed up first |
| `DetectN`, `DetectFileN`, `DetectOS` | the rule is only offered when a registry key / path exists, or on a minimum Windows version |
| `ActiveProcesses` | programs that lock the files: a note is shown, the rule still runs |
| `ExcludeKeyN=FILE\|path` / `PATH\|dir` | carve-outs inside a broader `FileKey` |
| `OnFileN=<pattern>\|FileDeleteIfOlderThan\|Ndays` | per-file age filter (also `Nhours`) |
| `ActionN=<name>[\|arg]` | built-in procedures (below) |
| `Warning`, `NeedsAdmin` | shown before ticking the rule / greyed out without administrator rights |

`[Rule Vars]` holds `NAME=path1,path2,…`, used as `<NAME>`: a path containing `<NAME>` expands to one path per
alternative, so a single rule covers every profile of a browser (`Default`, `Profile 1`, …). Paths also use
`%ENV%` variables plus a few extra ones (`%LocalLowAppData%`, `%Recent%`, `%Documents%`, `%Desktop%`).

**Actions:** `EmptyRecycleBin`, `CleanDNSCache`, `CleanClipboard`, `ShellAddToRecentDocs`,
`RemoveEmptyDirectories`, `CleanWindowsEventLogs`, and the browser-database actions `ChromiumHistory`,
`ChromiumDownloads`, `ChromiumCookies`, `ChromiumFormData`, `FirefoxHistory`, `FirefoxCookies`,
`FirefoxFormData`.

## 2. The cleaning pipeline

1. **Load** every rule into a `Rule`.
2. **Detect**: rules whose `Detect*` checks fail are shown as "not installed" and skipped.
3. **Apply** in one of two modes on the same code path: **Analyse** enumerates and counts, **Clean** also
   deletes. Analyse never calls a delete function.
4. Each rule returns a `RuleResult`: files, bytes, database records, registry items, notes and errors.

Safety rules in the engine: symlinks and junctions are never followed; drive roots and shallow recursive
paths are refused; files in use are skipped and counted; registry deletes are written to
`backups\registry_*.json` first.

## 3. Browser databases

History, downloads, cookies and form data are SQLite databases. `browserdb.py` deletes **rows**, not files:

* Chromium browsers keep bookmarks in a separate JSON file, so the history tables can be emptied safely
  (`meta` and the download tables are left for their own rule).
* Firefox keeps bookmarks and history together in `places.sqlite`: visits are removed, and a place is kept
  while a bookmark, keyword or bookmark annotation still points to it.
* Cookies whose host matches the **cookie allowlist** (a domain or any of its subdomains) are kept.
* Analyse reads a temporary copy; Clean opens the database with `BEGIN IMMEDIATE`, so a running browser
  produces "close it and run again" instead of a half-done clean. Afterwards the database is `VACUUM`ed.

## 4. Registry cleaner

`regscan.py` checks 10 categories (obsolete software, application paths, startup entries and their
enable/disable switches, MUI cache, shared DLLs, help files, sound events, installer folders, "open with"
applications, fonts). An entry is reported only when it names an absolute local path whose drive exists and
Windows answers *file not found*; network, removable, access-denied and WindowsApps paths are never judged,
and commands run through hosts such as rundll32 or msiexec are skipped. Fixes are written to a
`woof-registry-v2` JSON backup first, and any backup can be restored.

## 5. Other tools

| Tool | Mechanism |
|---|---|
| Startup apps | Run/RunOnce keys, Startup folders, logon/boot tasks; disable = Task Manager's `StartupApproved` flag |
| Windows services | `Win32_Service` to list, `sc.exe config/start/stop` in one elevated run; previous start types are backed up |
| Context menu | shell extensions disabled through `Shell Extensions\Blocked`, commands through `LegacyDisable`; deletes are backed up |
| Software Updater | `winget upgrade`; skipped versions and ignored apps are kept in settings |
| Driver Updater | Windows Update Agent API, restore point before installing; skipped updates and ignored devices in settings |
| Uninstaller | the program's own uninstaller (`msiexec /x` for MSI), then a leftover sweep to the Recycle Bin |
| Duplicate Finder | size → 64 KB head hash → full BLAKE2b hash |
| Scheduled cleaning | per-user Task Scheduler task registered from XML with `StartWhenAvailable` (a missed run catches up); sign-in schedules use `HKCU\…\Run`. It runs `auto-clean`, which cleans the Custom Clean selection |
| Start without UAC | an on-demand task with highest privileges, started with `schtasks /Run` |
| Self-update | GitHub Releases, SHA-256 verified before anything runs |
