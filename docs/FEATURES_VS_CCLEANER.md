# Woof Cleaner vs CCleaner 7: feature map

Source: the CCleaner 7.12 installed on this PC. The feature list comes from its own UI: the routes in
`gui\chunks\routes.js`, about 2,700 English UI strings in `gui\chunks\en.js` and the 768 rules in `ccleaner.ini`.
Licence-gated features were not run, so their descriptions come from the UI text, not from testing.

Legend: ✅ in Woof · ◐ partly · ❌ not yet

| CCleaner 7 | What it does there | Woof 0.4 |
|---|---|---|
| Custom Clean | 768 rules: Windows, System, Advanced, browsers, apps, AI tools, Windows Store, Downloads | ✅ same engine and rule format, 75 original rules |
| ↳ Registry cleaner | invalid entries: obsolete software, app paths, startup, MUI cache, shared DLLs, help, sounds, installers, fonts, type libraries, services, firewall rules … | ◐ 10 categories (services, type libraries, firewall rules, file extensions deliberately left out) |
| ↳ Browser databases | history, downloads, cookies, form data, session, site preferences, saved passwords/cards, compact databases | ◐ history, downloads, cookies, form data (passwords/cards deliberately not offered) |
| ↳ Cookie allowlist | keep cookies of trusted sites, add popular sites | ✅ |
| ↳ Secure deletion, ADS wipe, Wipe Free Space | multi-pass overwrite | ❌ |
| ↳ Include / exclude own folders in the UI | | ❌ (edit `rules.ini`) |
| ↳ Shut down after cleaning, run at startup | | ◐ run at sign-in via Scheduled Cleaning |
| ↳ Export results to CSV | | ❌ |
| Health Check | one scan for privacy + space + issues, health score | ❌ |
| Performance Optimizer | "sleep mode" for background apps | ❌ |
| Startup Manager | startup apps, scheduled tasks, Windows services, context menu | ✅ |
| Software Remover | uninstall + leftovers, temporary uninstall (restore within 30/90/120 days) | ◐ no temporary uninstall |
| Software Updater | update apps, skip version, ignore app | ✅ (winget) |
| Driver Updater | update, restore previous driver, skip/ignore, device categories, "what's wrong" wizard | ◐ no driver rollback or wizard |
| Duplicate Finder / Disk Analyzer | duplicates with type filters, CSV, space per file type | ◐ duplicates with type filter; no CSV, no space breakdown |
| Cloud Drive Cleaner | Google Drive, Gmail, OneDrive, Dropbox | ❌ |
| Scheduling | daily, weekly, every 2 weeks, at startup; missed runs catch up | ✅ |
| Statistics | space freed, items, cleans, updates over time | ◐ history of automatic cleans |
| Settings | theme, tray icon, skip UAC, Recycle Bin context menu, landing page, languages, auto-update, beta | ◐ theme, skip UAC, auto-update check |
| Pro Plus bundle | Recuva (file recovery), Speccy (system info) | ❌ |

## Suggested next steps

* **P2:** Health Check with a score; Statistics page; disk space per file type; CSV export and
  type filters for duplicates; wipe free space (`cipher /w`); driver rollback (`pnputil`); tray icon.
* **P3 (large):** Performance Optimizer sleep mode (needs a background monitor), temporary uninstall
  (snapshot files and registry), Cloud Drive Cleaner (OAuth app registrations), Recuva/Speccy-like tools.
