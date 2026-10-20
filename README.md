# 🐶 Woof Cleaner

A CCleaner-style PC toolkit for Windows, built after reverse-engineering CCleaner 7's architecture.
See [docs/HOW_CCLEANER_WORKS.md](docs/HOW_CCLEANER_WORKS.md) for what was found and how it maps here.

Pure Python 3.10+ standard library. No dependencies. It uses Windows' own tools (winget, Windows Update,
`Get-ScheduledTask`) where they exist.

## Install

Run **`dist\WoofCleaner-Setup-0.2.0.exe`** (~12 MB). The wizard lets you choose:

* **Only for me** (default, no admin) → `%LOCALAPPDATA%\Programs\Woof Cleaner`, or **all users** → `Program Files`
* Start Menu shortcut, optional Desktop shortcut, optional `woof` command on PATH
* An entry in *Settings → Apps* to uninstall (shortcuts, PATH and files are removed; your backups are kept)

Silent install for scripting: `WoofCleaner-Setup-0.2.0.exe /VERYSILENT /CURRENTUSER /TASKS="desktopicon,addtopath"`.

## Updates

Woof Cleaner updates itself from this repository's **GitHub Releases**:

* On start-up (at most once a day) and with the **Check for updates** button, the app asks GitHub for the
  latest release. If it's newer, it shows the release notes with *Update now / Later / Skip this version*.
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

`dist\WoofCleaner.exe` is a single self-contained file (~10 MB). Copy it to any 64-bit Windows 11 PC and
double-click it. **Python is not required**: the Python runtime, Tk and the rules are bundled inside.
`dist\woof.exe` is the same program for the command line.

* Settings and backups go to `%LOCALAPPDATA%\WoofCleaner\backups`.
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

| Tab | What it does | How |
|---|---|---|
| **Custom Clean** | temp files, caches, browser junk, Recycle Bin, traces | declarative rules in `data/rules.ini` (CCleaner's rule format), Analyze → Run Cleaner |
| **Uninstaller** | lists installed programs, runs their uninstaller, then sweeps leftovers | Uninstall registry keys (HKLM 64/32-bit + HKCU); MSI via `msiexec /x`; leftovers go to the Recycle Bin or a registry backup |
| **Startup** | enable, disable or delete startup programs | Run/RunOnce keys, Startup folders, logon/boot scheduled tasks; disable uses Task Manager's `StartupApproved` flag, so it is reversible |
| **Duplicate Finder** | finds files with identical content | size → 64 KB head hash → full BLAKE2b hash; auto-select keeps the oldest, newest or shortest-path copy; deletes to the Recycle Bin |
| **Software Updater** | finds newer versions of installed apps and installs them silently | `winget upgrade` |
| **Driver Updater** | Microsoft-certified driver updates and devices with driver problems | Windows Update Agent API (`Microsoft.Update.Session`) + `Win32_PnPSignedDriver` / `Win32_PnPEntity` |

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
python -m woofcleaner drivers [--list] [--scan] [--install]
```

Every destructive command asks first (`--yes` skips the question).
**Restart as administrator** in the GUI header (or an elevated prompt) unlocks `C:\Windows\Temp`, Prefetch,
HKLM startup entries, scheduled tasks and driver installs.

## Safety

* Cleaner: Analyze never deletes. Symlinks and junctions are never followed. Drive roots and shallow
  recursive paths are refused. The `%TEMP%` rule only removes files older than 24 h. Files in use are skipped.
* Registry, startup and leftover deletes are backed up to `backups\*.json` first. Files and folders from the
  Uninstaller, Startup and Duplicate Finder go to the **Recycle Bin** (undoable).
* Duplicate Finder refuses to delete every copy of a file. It skips cloud placeholders, which reading would
  download, and it skips system folders.
* Updaters only use Microsoft's own channels (the winget catalogue, Windows Update).

## Tests

```powershell
$env:PYTHONPATH = (Get-Location).Path
python -m unittest discover -s tests -v
```

File tests run in a temp directory. The Windows probes only read.
