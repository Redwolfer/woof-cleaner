"""User settings (settings.json in the user data folder), shared by every tool.

Keys in use:
  auto_check, last_check, skip_version   self-update (selfupdate.py)
  theme                                  "auto" | "light" | "dark"
  clean_selection                        rule ids ticked in Custom Clean (used by scheduled cleans)
  cookie_allowlist                       domains whose cookies survive browser cleaning
  sw_ignore, sw_skip                     Software Updater: ignored package ids / {id: skipped version}
  drv_ignore, drv_skip                   Driver Updater: ignored devices / skipped update ids
  auto_elevate                           start elevated through the scheduled task (no UAC prompt)
"""
from __future__ import annotations

import json
import threading

from . import paths

SETTINGS = paths.USER_DIR / "settings.json"
_lock = threading.Lock()

DEFAULT_ALLOWLIST = ["google.com", "accounts.google.com", "youtube.com", "github.com", "microsoft.com",
                     "live.com", "outlook.com"]


def load() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(**changes) -> dict:
    with _lock:
        s = load()
        s.update(changes)
        try:
            SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS.write_text(json.dumps(s, indent=1), encoding="utf-8")
        except OSError:
            pass
        return s


def get(key: str, default=None):
    return load().get(key, default)


def cookie_allowlist() -> list[str]:
    return list(get("cookie_allowlist", DEFAULT_ALLOWLIST))


def normalise_domain(text: str) -> str:
    """'https://www.Example.com/path' -> 'example.com'."""
    d = text.strip().lower()
    for prefix in ("https://", "http://"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    d = d.split("/", 1)[0].split(":", 1)[0].lstrip(".")
    return d[4:] if d.startswith("www.") else d


def domain_allowed(host: str, allowlist: list[str]) -> bool:
    """Cookie host ('.mail.google.com') matches an allowlisted domain or one of its subdomains."""
    h = host.lower().lstrip(".")
    return any(h == d or h.endswith("." + d) for d in allowlist if d)
