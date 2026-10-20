# Roadmap

Legend: ✅ done · ◐ partly · ❌ not yet

| Area | Woof 0.4 |
|---|---|
| Rule-based junk cleaning (75 rules: Windows, browsers, apps, AI tools, Store apps, developer caches) | ✅ |
| Browser history, downloads, cookies (with allowlist), form data, row by row | ✅ |
| Saved passwords / cards cleaning | ❌ deliberately not offered |
| Secure deletion, alternate data streams, wipe free space | ❌ |
| Include / exclude your own folders from the UI | ❌ (edit `rules.ini`) |
| Export results to CSV | ❌ |
| Registry cleaner | ◐ 10 categories; services, type libraries, firewall rules and file associations are deliberately left out |
| Startup apps, scheduled tasks, Windows services, context menu | ✅ |
| Uninstaller with leftover sweep | ✅ |
| Temporary uninstall (restore within N days) | ❌ |
| Software updates with skip / ignore | ✅ |
| Driver updates with skip / ignore | ✅ |
| Driver rollback, "what is wrong" troubleshooting wizard | ❌ |
| Duplicate finder | ◐ type filter; no CSV export |
| Disk space per file type | ❌ |
| Scheduled cleaning (daily / weekly / every 2 weeks / sign-in) | ✅ |
| One-click health check with a score | ❌ |
| Statistics over time | ◐ history of automatic cleans |
| Background-app sleep mode | ❌ |
| Cloud storage cleaning (Google Drive, OneDrive, Dropbox) | ❌ |
| Themes, start without UAC prompt, self-update | ✅ |
| Tray icon, languages | ❌ |

## Next

* **Soon:** health check with a score, statistics page, disk space per file type, CSV export and more
  duplicate filters, wipe free space (`cipher /w`), driver rollback (`pnputil`), tray icon.
* **Later (large):** background-app sleep mode (needs a monitor process), temporary uninstall (snapshot files
  and registry), cloud storage cleaning (OAuth app registrations), file recovery and system information tools.
