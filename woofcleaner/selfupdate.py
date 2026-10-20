"""Self-update from GitHub Releases.

Release layout expected (release.ps1 produces it):
    tag  v<version>
    WoofCleaner-Setup-<version>.exe   installer (used when the app was installed)
    WoofCleaner.exe                   portable build (used when running the portable exe)
    SHA256SUMS.txt                    "<sha256>  <file name>" lines
Every download is verified against SHA-256 before it is run; without a hash nothing is installed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import UPDATE_REPO, __version__, paths, winutil

API = "https://api.github.com/repos/{repo}/releases/latest"
ALLOWED_HOSTS = ("https://github.com/", "https://objects.githubusercontent.com/",
                 "https://release-assets.githubusercontent.com/")
SETTINGS = paths.USER_DIR / "settings.json"
CHECK_INTERVAL = 24 * 3600


@dataclass
class Asset:
    name: str
    url: str
    size: int
    sha256: str = ""


@dataclass
class Release:
    version: str
    tag: str
    notes: str
    page: str
    assets: dict[str, Asset] = field(default_factory=dict)

    @property
    def setup(self) -> Asset | None:
        return next((a for n, a in self.assets.items() if re.fullmatch(r"(?i)woofcleaner-setup-.*\.exe", n)), None)

    @property
    def portable(self) -> Asset | None:
        return self.assets.get("WoofCleaner.exe")


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v.lstrip("vV").split("-")[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(remote: str, local: str | None = None) -> bool:
    return parse_version(remote) > parse_version(local or __version__)


# ---- settings ------------------------------------------------------------------------

def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(**changes) -> dict:
    s = load_settings()
    s.update(changes)
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(s, indent=1), encoding="utf-8")
    except OSError:
        pass
    return s


def auto_check_due() -> bool:
    s = load_settings()
    return bool(UPDATE_REPO) and s.get("auto_check", True) and time.time() - s.get("last_check", 0) > CHECK_INTERVAL


# ---- GitHub ---------------------------------------------------------------------------

def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"WoofCleaner/{__version__}",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest_release(repo: str = UPDATE_REPO) -> Release:
    if not repo:
        raise RuntimeError("No update repository configured (UPDATE_REPO in woofcleaner/__init__.py).")
    data = json.loads(_get(API.format(repo=repo)))
    rel = Release(version=data["tag_name"].lstrip("vV"), tag=data["tag_name"], notes=data.get("body") or "",
                  page=data.get("html_url", f"https://github.com/{repo}/releases"))
    sums_url = None
    for a in data.get("assets", []):
        digest = a.get("digest") or ""  # GitHub fills "sha256:<hex>" for uploaded assets
        rel.assets[a["name"]] = Asset(a["name"], a["browser_download_url"], a.get("size", 0),
                                      digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else "")
        if a["name"].upper() == "SHA256SUMS.TXT":
            sums_url = a["browser_download_url"]
    if sums_url:
        for line in _get(sums_url).decode("utf-8", "replace").splitlines():
            m = re.match(r"([0-9a-fA-F]{64})\s+\*?(.+)", line.strip())
            if m and m.group(2).strip() in rel.assets:
                rel.assets[m.group(2).strip()].sha256 = m.group(1).lower()
    return rel


def check(repo: str = UPDATE_REPO) -> Release | None:
    """The newer release, or None when up to date. Records the check time."""
    rel = latest_release(repo)
    save_settings(last_check=time.time())
    return rel if is_newer(rel.version) else None


# ---- install kinds ---------------------------------------------------------------------

def install_kind() -> str:
    """'installed' (Inno Setup install), 'portable' (frozen exe elsewhere) or 'source'."""
    if not paths.FROZEN:
        return "source"
    return "installed" if (paths.EXE_DIR / "unins000.exe").exists() else "portable"


def download(asset: Asset, progress: Callable[[int, int], None] = lambda done, total: None) -> Path:
    if not asset.url.startswith(ALLOWED_HOSTS):
        raise RuntimeError(f"refusing to download from an unexpected host: {asset.url}")
    if not asset.sha256:
        raise RuntimeError("the release has no SHA-256 checksum for this file - not installing it")
    dest = Path(tempfile.mkdtemp(prefix="woof_update_")) / asset.name
    h = hashlib.sha256()
    req = urllib.request.Request(asset.url, headers={"User-Agent": f"WoofCleaner/{__version__}"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or asset.size or 0)
        done = 0
        while chunk := r.read(256 * 1024):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            progress(done, total)
    if h.hexdigest() != asset.sha256:
        dest.unlink(missing_ok=True)
        raise RuntimeError("downloaded file does not match its SHA-256 checksum - update aborted")
    return dest


def apply(rel: Release, file: Path) -> None:
    """Start the update. The caller must exit right after this returns."""
    kind = install_kind()
    if kind == "installed":
        in_program_files = any(str(paths.EXE_DIR).lower().startswith(os.environ.get(v, "~").lower())
                               for v in ("ProgramFiles", "ProgramFiles(x86)"))
        args = (f'/SILENT /SUPPRESSMSGBOXES /NORESTART /RELAUNCH=1 {"/ALLUSERS" if in_program_files else "/CURRENTUSER"} '
                f'/DIR="{paths.EXE_DIR}"')
        winutil.shell_execute(str(file), args, wait=False)
    elif kind == "portable":
        _swap_portable(file)
    else:
        raise RuntimeError("Running from source: update with git pull instead.")


def _swap_portable(new_exe: Path) -> None:
    """Replace the running portable exe once this process (and its one-file launcher) has exited."""
    old = Path(sys.executable)
    pids = {os.getpid(), os.getppid()}
    waits = "\n".join(
        f':w{p}\ntasklist /FI "PID eq {p}" 2>nul | find "{p}" >nul && (timeout /t 1 /nobreak >nul & goto w{p})'
        for p in pids)
    script = Path(tempfile.gettempdir()) / f"woof_swap_{os.getpid()}.cmd"
    script.write_text(
        f'@echo off\n{waits}\nmove /y "{new_exe}" "{old}" >nul\nstart "" "{old}"\ndel "%~f0"\n', encoding="ascii")
    winutil.shell_execute("cmd.exe", f'/c "{script}"', wait=False, show=0)
