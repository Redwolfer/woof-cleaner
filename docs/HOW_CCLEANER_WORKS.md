# How CCleaner 7 cleans (as observed on this machine)

Target: `C:\Program Files\Piriform\CCleaner 7` — CCleaner 7.12.1526.1963 (Piriform / Gen Digital).

**Evidence labels:** *Observed* = read directly from a shipped file or the product's own logs.
*Inferred* = a conclusion drawn from observations. *Unknown* = not established.

> **Limits of this investigation.** REA's native decompiler backends (Ghidra, IDA, Hopper, Kuna) are not
> configured on this PC, so no function was decompiled. I did not install them. The findings come from REA's
> backend-free tools (`inspect_pe_resources`, `inspect_rust_binary`, `open_binary`), plus direct reads of the
> rule file, the binaries' string tables and the product's own log files. REA's `analyze_javascript_application`
> run on the `gui\` folder timed out, so I did not use it.

## 1. The big picture

CCleaner is three layers. The cleaning logic is data-driven.

```
 CCleaner.exe  (7.6 MB)          WebView2 shell: renders gui\*.html/js (Svelte/Vite bundle)
      │  IPC (local service connection)
      ▼
 CCleaner_service.exe (32 MB)    C++ engine, namespace asw::cleaning::v0_10
      │  reads
      ▼
 ccleaner.ini  (495 KB, 768 rules)   <- the actual knowledge of "what is junk"
```

* **Observed:** `CCleaner.exe` has only 9 PE resources: icons, a manifest and 3 small blobs (REA evidence
  `ev_809bf1ca…d8e31`). It carries no cleaning data.
* **Observed:** `gui\` holds `index.html`, `frame.html` and Vite/Svelte JS chunks. The UI is a web page in
  WebView2.
* **Observed:** All cleaning log lines come from `CCleaner_service.exe`'s `ccleaner_service.log`, category
  `Windows.Cleaning`. Its string table has the C++ classes `ICleanerCore`, `CleanerCoreImpl`,
  `ICleanerSync` and `CleanerSyncST` in `asw::cleaning::v0_10`, and a source path
  `features\cleaning\src\cleaning\DiskCleanup.cpp`.
* **Observed:** The service is a mixed binary. It has C++ cleaning code and Rust crates
  (`ccleaner_service::server::background_scan`, `…::opm`, `…::statistics`). REA found no `.dep-v0` Rust
  dependency section, so the crate list is **unknown** (`ev_db551a10…a3c`).
* **Observed:** the cleaning log lines come from the service process, not the UI. **Inferred:** the service
  does the deleting and runs with elevated rights, which is how it can clean `C:\Windows\Temp`. The IPC
  protocol between UI and service is **unknown**.

## 2. The rule file is the product

`ccleaner.ini` is plain-text INI, 769 sections: one `[Rule Vars]` section and 768 rules. The service log
confirms the loader: `CreateTasksFromINI - created 768 tasks` and `parsing '{}' for Rule Vars`
(the second is a string in the binary).

### Rule anatomy (every key below appears in the shipped file)

| Key | Count | Meaning |
|---|---|---|
| `ID`, `Author`, `Tags`, `Default` | 768 each | stable id (`windows.tempfiles`), UI grouping, pre-ticked or not (422 true / 333 false) |
| `FileKeyN=<dir>\|<patterns>\|<flags>` | 3050 | files to delete. Patterns are `;`-separated. Flags are `RECURSE` and/or `REMOVESELF` |
| `RegKeyN=<key>[\|<value>]` | 1168 | registry key or value to delete. Almost all are `HKCU` (1152 HKCU vs 11 HKLM) |
| `DetectFileN` / `DetectN` | 528 / 449 | rule only applies if a path or registry key exists, so uninstalled apps are hidden |
| `DetectOS` | 9 | minimum Windows NT version (`6.0` = Vista) |
| `ActiveProcesses`, `MaxProcessStopTimeout` | 261 / 66 | processes that lock the files (the engine warns) |
| `ExcludeKeyN=FILE\|path` / `PATH\|dir` | 56 | carve-outs inside a broader `FileKey` |
| `OnFileN=<pattern>\|<handler>[\|arg…]` | 641 | per-file handler. Observed handlers are below |
| `ActionN=<name>[\|arg]` | 72 | built-in procedural cleaners, for jobs that are not "delete files" |
| `WarningRef` | 87 | id of a localized warning shown before the rule runs |

* **Rule Vars** (`[Rule Vars]`): `NAME=path1,path2,…`, used as `<NAME>`. A key containing `<NAME>` expands to
  one concrete path per alternative. Example: `GOOGLE_CHROME_PROFILE_FOLDERS` lists Chrome, Chrome Beta,
  Chromium, Yandex, Torch and more. One browser rule covers every Chromium fork. The binary refuses duplicate
  var definitions (`multiple Cleaning Rule Vars are not supported`).
* **Environment tokens** most used in paths: `%localappdata%` (929), `%appdata%` (724), `%userprofile%` (209),
  `%programfiles%` (194), `%commonappdata%` (172), `%windir%` (54), plus CCleaner-specific ones such as
  `%LocalLowAppData%`, `%Recent%`, `%Documents%` and `%HF_HOME%`.
* **OnFile handlers observed:** `FileDelete` and `FileDeleteIfOlderThan|Ndays`. The older-than handler is used,
  for example, for Prefetch (`*|FileDeleteIfOlderThan|14days`). Browser SQLite handlers are `HistoryGeneral`,
  `HistoryDownloads|<tables…>`, `HistoryShortcuts`, `HistoryPreferences`, `HistoryKeywords` and
  `LastDownloadLocationJSON`.
* **Actions observed (14 kinds):** `Registry` (15), `CommonLastVisited` (15), `DiskCleanup` (12),
  `CleanOfficeMRU` (11), `CleanCredentials` (7), `RemoveEmptyDirectories` (3), `EmptyRecycleBin`,
  `CleanClipboard`, `CleanEnvironmentPath`, `ShellAddToRecentDocs`, `CleanDNSCache`,
  `CleanWindowsEventLogs`, `CleanNetworkPasswords`, `TaskbarJumpLists`.

Examples straight from the file:

```ini
[Old Prefetch data]
Detect=HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\OptimalLayout
OnFile1=*|FileDeleteIfOlderThan|14days
FileKey1=%windir%\Prefetch|*.pf|RECURSE

[Empty Recycle Bin]
Action1=EmptyRecycleBin

[Thumbnail Cache]
FileKey1=%LocalAppData%\Microsoft\Windows\Explorer|thumbcache_*.db
Action1=DiskCleanup|Thumbnail Cache
```

## 3. The execution pipeline

All of this is from `ccleaner_service.log`. The same strings exist in the binary.

1. **Load.** At service start: `CreateTasksFromINI - created 768 tasks`. Each rule becomes a task. Bad entries
   are reported by name, for example `OnFile entry '{}' contains an unknown …` and
   `unable to determine MaxProcessStopTimeout`.
2. **Detect.** `CleanerSyncST::DetectApplicable` and `::DetectActiveProcess` are separate operations.
   A rule whose `Detect*` fails is dropped. If `ActiveProcesses` are running, the log says
   `Google Chrome - Cookies is currently running, cleaning will be suboptimal`. It warns but still runs.
3. **Apply in one of two modes.** `CleanerSync Apply - 4 tasks, mode 'Analyse'` runs first, then
   `Applying Rule 'CCleaner - Temporary Files' in Analyse mode` per rule, then
   `CleanerSync Apply complete - 4 rule results, cancelled: false`. The mode flag is the only difference
   between "Analyze" and "Run Cleaner". The *inferred* corollary is that Analyse uses the same enumeration code
   and only skips the delete call. `Cannot start CleanerSyncST::… while an operation is running` shows that
   one operation runs at a time and that cancel is supported.
4. **Per-rule result.** Each rule returns a result, bytes and file counts, with a "results style"
   (`'Detailed'` in the log). That feeds the UI list.
5. **Housekeeping.** `CleanerSync ClearUserCache` runs between operations.

### Delete primitives (observed in the string table and import names)

| Task | API / mechanism |
|---|---|
| Files | `FileDelete` handler; `MoveFileExW` is imported (the standard delete-on-reboot call). Whether it is used for locked files is **unknown** |
| Registry | `RegDeleteKeyExW`, `RegDeleteKeyW`, `RegDeleteKeyValueW`, `RegDeleteValueW` |
| Recycle Bin | `SHEmptyRecycleBinW` |
| DNS cache | `DnsFlushResolverCache` |
| Windows built-in cleanup | `DiskCleanup` action (`DiskCleanup purged N bytes from volume 'Thumbnail Cache'` in the log) |
| Empty folders | `RemoveEmptyDirectoriesFromAction - pruning empty directories under '{}'` |
| Browser SQLite | embedded SQLite (`wal_checkpoint`, `VACUUM`). Log shows `CleanTable table 'visits'`, `'urls'`, `'keyword_search_terms'`. It deletes rows, not whole files, so bookmarks survive: `History CleanTableExcludingBookmarks for table 'urls'`. It fails with `database is locked` while the browser runs |
| Free-space wipe | `wipe_free_space` and `wipe_mft_free_space` options exist in the service. They are a separate "Drive Wiper" feature, not part of normal rules |

A safety net is **observed**: `data\RegistryBackup\cc_<timestamp>.reg` files are written before registry
cleaning, so a deleted key can be restored.

### Why a service?

**Inferred:** Rules touch `C:\Windows\Temp`, `C:\Windows\Prefetch`, `HKLM`, event logs and other users' profiles
(the `AdditionalUsers` rule key exists). Those need elevation, so a privileged service does the work.
The WebView UI only sends requests and renders results.

## 4. Not about cleaning, but in the same service (noted for completeness)

`background_scan` and `background_cleanup` schedulers (Driver Updater, Performance Optimizer, Uninstaller
scans), an `opm` module, statistics/analytics workers and Avast/AVG installer offers in `data\config.def`
(this is a promotional config, not cleaning data). None of this is needed for a cleaner clone, and the clone
omits it.

## 5. What Woof Cleaner reproduces

| CCleaner mechanism | Woof Cleaner |
|---|---|
| INI rules → tasks | `woofcleaner/rules.py` parses the same keys (`FileKey`, `RegKey`, `Detect*`, `ExcludeKey`, `OnFile`, `Action`, `[Rule Vars]`) |
| `<VAR>` and `%ENV%` expansion | `engine.expand_variants` / `expand_env` |
| Detect before offering a rule | `engine.is_applicable` (path, registry key, OS version) |
| Analyse vs Clean mode on one code path | `Context.mode`; analyse never calls delete |
| `ActiveProcesses` warning | runs `tasklist`, adds a note, still runs |
| `RECURSE` / `REMOVESELF` / patterns | `engine._clean_filekey` |
| `FileDeleteIfOlderThan` | `engine._per_file_policy` |
| Recycle Bin, DNS, clipboard, recent docs, empty dirs | `winutil` + `engine._action` |
| Registry delete with backup | JSON backup in `backups\` before deleting (HKCU only) |
| Per-rule results | `RuleResult` |

**Not implemented (deliberately):** browser SQLite surgery (history, cookies by row), `DiskCleanup` COM
handlers, event-log clearing, credential cleaning, the `HKLM` registry, secure free-space wiping, and scheduled background cleaning. The Uninstaller, Startup manager, Duplicate Finder, Software Updater and Driver Updater exist as separate tools; see the README. They use Windows' own channels (winget, Windows Update), not CCleaner's back ends.

**Design choices that are mine, not CCleaner's:** never follow symlinks or junctions; refuse drive roots and
shallow recursive paths; HKCU only; the rule set is my own original `data\rules.ini`, not a copy of
Gen Digital's copyrighted file.

**Documented elsewhere but not directly observed in this investigation:** the exact meaning of `RECURSE`
(descend into subfolders) and `REMOVESELF` (also remove the folder itself). Woof Cleaner follows the usual
reading of these flags, which the rule names support.
