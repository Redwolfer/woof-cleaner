# 🐶 Woof Cleaner

A rule-driven PC cleaner and toolkit for Windows. **1.0.0** is the first stable version of the series that began at **0.1.0**.
See [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) for the architecture and [docs/ROADMAP.md](docs/ROADMAP.md) for what is next.
The [LLM project guide](AGENTS.md) maps user workflows to code and links to the [CCleaner research](docs/CCLEANER_RESEARCH.md).

Pure Python 3.10+ standard library. No dependencies. It uses Windows' own tools (winget, Windows Update,
`Get-ScheduledTask`) where they exist.

## Install

To move from the previous 0.3.0 or 0.4.0 series, run the new installer once using the same install scope.

Run **`dist\fresh-v<version>\WoofCleaner-Setup-<version>.exe`**. The wizard offers the following choices.

* **Only for me** (default, no admin) → `%LOCALAPPDATA%\Programs\Woof Cleaner`, or **all users** → `Program Files`
* Start Menu shortcut, optional Desktop shortcut, optional `woof` command on PATH
* An entry in *Settings → Apps* to uninstall (shortcuts, PATH, files and scheduled cleans are removed; your backups are kept)

Silent install for scripting: `WoofCleaner-Setup-<version>.exe /VERYSILENT /CURRENTUSER /TASKS="desktopicon,addtopath"`.

## Updates

Woof Cleaner updates itself from this repository's **GitHub Releases**:

* On start-up (at most once a day) and with the **Check for updates** button, the app asks GitHub for the
  latest release. The new series uses tags such as `fresh-v0.1.0`. If a release in this series is newer, it shows the release notes with *Update now / Later / Skip this version*.
* **Update now** downloads the installer, verifies its **SHA-256**, runs it silently into the same folder, and
  restarts the new version. Portable copies swap the exe in place. A file without a matching checksum is never run.
* Command line: `woof update` (or `woof update --check`).

**Publishing a new version** (maintainer):

```powershell
# 1. bump __version__ in woofcleaner\__init__.py, commit
# 2. build, tag, push and publish the release with installer + portable exe + SHA256SUMS.txt
.\release.ps1 -Notes "What's new in this version"
```

## Portable (no install)

`dist\fresh-v<version>\WoofCleaner.exe` is a single self-contained file. Copy it to any 64-bit Windows 11 PC and
double-click it. **Python is not required**: the Python runtime, Tk and the rules are bundled inside.
`dist\fresh-v<version>\woof.exe` is the same program for the command line.

* Settings live in `%LOCALAPPDATA%\WoofCleaner\settings.json`. Registry backups live in the adjacent `backups` folder.
* To customise cleaning rules without rebuilding, put an edited `rules.ini` next to the `.exe`.
* The exe is not code-signed, so Windows SmartScreen may show "Windows protected your PC" the first time
  (click *More info → Run anyway*). Signing it with a code-signing certificate removes that warning.

Rebuild the exes and the installer after code changes. The build machine needs Python,
`pip install pyinstaller` and, for the installer, `winget install JRSoftware.InnoSetup`.
The version comes from `woofcleaner/__init__.py`.

```powershell
.\build.ps1
```

From source:

```powershell
python -m woofcleaner            # opens the GUI
```

## Tools

The window has a sidebar grouped by task (Clean / Speed up / Fix & update / Manage), a light and a dark
theme (or *Match Windows*), and Ctrl+1 … Ctrl+9 to jump between pages.

| Page | What it does | How |
|---|---|---|
| **Custom Clean** | temp files, caches, browser history / downloads / cookies / form data, Recycle Bin, event logs, AI-tool caches, Store app caches … (75 rules) | declarative rules in `data/rules.ini`, Analyze → Run Cleaner. Browser databases are cleaned **row by row** (bookmarks and allowlisted cookies survive). The ticked items are remembered and used by scheduled cleans |
| **Registry** | finds entries that point to missing programs/files: obsolete software, app paths, startup entries, MUI cache, shared DLLs, help files, sound events, installer folders, "open with" apps, fonts | only reports an absolute local path that certainly does not exist; backs up to `backups\registry_issues_*.json` first; **Restore a backup** writes any backup back |
| **Duplicate Finder** | finds files with identical content | size → 64 KB head hash → full BLAKE2b hash; auto-select keeps the oldest, newest or shortest-path copy; deletes to the Recycle Bin |
| **Startup Manager** | *Startup apps* (Run keys, Startup folders, logon tasks), *Windows services* (start type, start/stop), *Context menu* (right-click entries) | disable = Task Manager's `StartupApproved` flag, `sc config`, `Shell Extensions\Blocked` / `LegacyDisable`; all reversible, deletes are backed up |
| **Software Updater** | finds newer versions of installed apps and installs them silently; **Skip this version** / **Ignore app** | `winget upgrade` |
| **Driver Updater** | Microsoft-certified driver updates, devices with driver problems; **Skip update** / **Ignore device** | Windows Update Agent API (`Microsoft.Update.Session`) + `Win32_PnPSignedDriver` / `Win32_PnPEntity` |
| **Uninstaller** | lists installed programs, runs their uninstaller, then sweeps leftovers | Uninstall registry keys (HKLM 64/32-bit + HKCU); MSI via `msiexec /x`; leftovers go to the Recycle Bin or a registry backup |
| **Scheduled Cleaning** | daily, weekly, every 2 weeks or at every sign-in; recent scans and manual or automatic cleans | per-user Task Scheduler task with *run when available* (a missed run happens when the PC is next on); sign-in uses `HKCU\…\Run` |
| **PC overview** | Health Check, disk usage by extension and daily activity | Health Check previews selected rules and enabled startup apps. Disk usage scans a folder on request. Statistics sum reclaimed bytes from completed work, including partial runs |
| **Settings** | theme, cookie allowlist, start as administrator **without a UAC prompt**, update checks, data folder | the no-UAC start is an on-demand task with highest privileges, created once from an elevated window |

In Custom Clean, use **Folders** to include folders or protect a subtree during file scans. Tick **Custom folders** to include those files in a clean. Custom Clean exports summary and listed details to CSV. Duplicate Finder exports each copy and its latest move result. On smaller windows the **Tool** dropdown provides access to every page.

## Command line

```powershell
python -m woofcleaner list                          # cleaning rules ([x] = default)
python -m woofcleaner analyze [--all] [-v]          # dry run
python -m woofcleaner clean --rules discord.cache   # analyse, ask, delete
python -m woofcleaner programs --search zoom
python -m woofcleaner uninstall "7-Zip"             # vendor uninstaller + leftover sweep
python -m woofcleaner startup --tasks               # numbered list
python -m woofcleaner startup --disable 4
python -m woofcleaner dupes D:\Photos --min-size 500KB --ext jpg,png [--delete oldest]
python -m woofcleaner updates [--install Git.Git | --all]
python -m woofcleaner updates --skip Git.Git | --ignore Zoom.Zoom | --resume Zoom.Zoom
python -m woofcleaner drivers [--list] [--scan] [--install] [--skip N | --ignore N]
python -m woofcleaner registry [--category muicache,startup] [--fix]   # scan; --fix backs up first
python -m woofcleaner registry --backups | --restore backups\registry_issues_....json
python -m woofcleaner schedule --add biweekly --day Friday --time 09:30   # daily|weekly|biweekly|logon
python -m woofcleaner schedule [--enable ID | --disable ID | --run ID | --remove ID]
python -m woofcleaner services [--all] [--set Spooler demand | --start NAME | --stop NAME]
python -m woofcleaner contextmenu [--all] [--disable N | --enable N | --delete N]
python -m woofcleaner auto-clean                    # what a schedule runs: the saved selection, no questions
```

The interactive `clean` command previews selected items and asks for confirmation. Pass `--yes` to confirm in advance. Scheduled jobs use `auto-clean` and the saved selection.
**Restart as administrator** in the GUI header (or an elevated prompt) unlocks `C:\Windows\Temp`, Prefetch,
HKLM startup entries, scheduled tasks and driver installs.

## Safety

* Cleaner: Analyze never deletes. Symlinks and junctions are never followed. Drive roots and shallow
  recursive paths are refused. The `%TEMP%` rule only removes files older than 24 h. Files in use are skipped.
* Registry Fix writes its JSON backup before applying changes. Custom Clean saves a recoverable snapshot of the selected registry targets before deleting any of them. Files and folders from the
  Uninstaller, Startup and Duplicate Finder go to the **Recycle Bin** (undoable).
* Duplicate Finder refuses to delete every copy of a file. It skips cloud placeholders, which reading would
  download, and it skips system folders.
* Updaters only use Microsoft's own channels (the winget catalogue, Windows Update).
* Browser cleaning deletes database rows, never whole profiles: bookmarks, settings, saved passwords and the
  cookies of allowlisted sites are kept. A browser that is running locks its database; Woof says "close it and run
  again" instead of forcing it.
* The registry cleaner never judges network, removable, access-denied or WindowsApps paths, skips commands run
  through hosts such as rundll32/msiexec, and leaves services, file associations and firewall rules alone.
  HKLM issues need administrator rights.
* Scheduled cleans use the saved Custom Clean selection. Defaults apply on first use. An empty or entirely obsolete selection schedules zero rules. Non-elevated runs skip rules that require administrator rights.

## Tests

```powershell
$env:PYTHONPATH = (Get-Location).Path
python -m unittest discover -s tests -v
```

File tests run in a temp directory. The Windows probes only read.
