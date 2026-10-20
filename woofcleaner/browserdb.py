"""Row-level cleaning of browser SQLite databases (history, downloads, cookies, form data).

Rows are deleted instead of whole files, so bookmarks, settings and allowlisted cookies survive.

* Chromium (Chrome, Edge, Brave, Opera, Vivaldi): bookmarks live in a separate JSON file, so emptying the
  history tables never touches them.
* Firefox: bookmarks and history share places.sqlite. Visits are removed, and a place row is kept when a
  bookmark, keyword or bookmark annotation still points to it.

Browsers lock their databases while running. Analyse reads a temporary copy; Clean needs the browser closed
and reports "close <browser>" instead of failing.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from typing import Callable

from .settings import domain_allowed

# Chromium "History" tables that are not browsing history.
_CHROMIUM_KEEP = {"meta", "downloads", "downloads_url_chains", "downloads_slices"}
_DOWNLOAD_TABLES = ["downloads", "downloads_url_chains", "downloads_slices"]


@dataclass
class Job:
    db: str                         # path relative to the profile folder
    tables: list[str] | None        # tables to empty; None = every table except _CHROMIUM_KEEP
    count_table: str                # rows reported to the user
    cookie_column: str = ""         # set for cookie tables: rows whose host is allowlisted are kept


@dataclass
class DbResult:
    records: int = 0
    bytes_freed: int = 0
    notes: list[str] = field(default_factory=list)
    items: list[tuple[str, int]] = field(default_factory=list)   # (db path, records)


JOBS: dict[str, list[Job]] = {
    "chromiumhistory": [Job("History", None, "urls"), Job("Shortcuts", ["omni_box_shortcuts"], "omni_box_shortcuts"),
                        Job("Top Sites", ["top_sites", "thumbnails"], "top_sites")],
    "chromiumdownloads": [Job("History", _DOWNLOAD_TABLES, "downloads")],
    "chromiumcookies": [Job(os.path.join("Network", "Cookies"), ["cookies"], "cookies", "host_key"),
                        Job("Cookies", ["cookies"], "cookies", "host_key")],
    "chromiumformdata": [Job("Web Data", ["autofill"], "autofill")],
    "firefoxhistory": [Job("places.sqlite", [], "moz_historyvisits")],   # special-cased below
    "firefoxcookies": [Job("cookies.sqlite", ["moz_cookies"], "moz_cookies", "host")],
    "firefoxformdata": [Job("formhistory.sqlite", ["moz_formhistory"], "moz_formhistory")],
}
ACTIONS = set(JOBS)


def _tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _count(con: sqlite3.Connection, job: Job, allowlist: list[str]) -> int:
    if job.count_table not in _tables(con):
        return 0
    if job.cookie_column:
        con.create_function("woof_allowed", 1, lambda h: 1 if domain_allowed(h or "", allowlist) else 0)
        sql = f"SELECT COUNT(*) FROM {_q(job.count_table)} WHERE woof_allowed({_q(job.cookie_column)}) = 0"
    else:
        sql = f"SELECT COUNT(*) FROM {_q(job.count_table)}"
    return con.execute(sql).fetchone()[0]


def _firefox_history(con: sqlite3.Connection) -> None:
    have = _tables(con)
    keep = ("SELECT fk FROM moz_bookmarks WHERE fk IS NOT NULL"
            + (" UNION SELECT place_id FROM moz_keywords" if "moz_keywords" in have else ""))
    for t in ("moz_historyvisits", "moz_inputhistory", "moz_places_metadata", "moz_places_metadata_search_queries"):
        if t in have:
            con.execute(f"DELETE FROM {t}")
    if "moz_annos" in have:
        con.execute(f"DELETE FROM moz_annos WHERE place_id NOT IN ({keep})")
    con.execute(f"DELETE FROM moz_places WHERE id NOT IN ({keep})")
    con.execute("UPDATE moz_places SET visit_count = 0, last_visit_date = NULL")
    if "moz_origins" in have:
        con.execute("DELETE FROM moz_origins WHERE id NOT IN (SELECT origin_id FROM moz_places WHERE origin_id IS NOT NULL)")


def _clean(con: sqlite3.Connection, action: str, job: Job, allowlist: list[str]) -> None:
    if action == "firefoxhistory":
        _firefox_history(con)
        return
    have = _tables(con)
    tables = [t for t in have if t not in _CHROMIUM_KEEP] if job.tables is None else [t for t in job.tables if t in have]
    for t in tables:
        if job.cookie_column and t == job.count_table:
            con.execute(f"DELETE FROM {_q(t)} WHERE woof_allowed({_q(job.cookie_column)}) = 0")
        else:
            con.execute(f"DELETE FROM {_q(t)}")


def _is_locked(e: sqlite3.Error) -> bool:
    msg = str(e).lower()
    return "locked" in msg or "busy" in msg or "unable to open" in msg


def _analyse_copy(db: str) -> str:
    """Copy a (possibly locked) database and its WAL into a temp folder so it can be read safely."""
    tmp = tempfile.mkdtemp(prefix="woofdb_")
    dst = os.path.join(tmp, "db.sqlite")
    shutil.copyfile(db, dst)
    if os.path.exists(db + "-wal"):
        shutil.copyfile(db + "-wal", dst + "-wal")
    return dst


def process(action: str, profile: str, clean: bool, allowlist: list[str],
            label: str = "", is_cancelled: Callable[[], bool] = lambda: False) -> DbResult:
    """Count (analyse) or delete (clean) the rows `action` covers in one browser profile folder."""
    res = DbResult()
    seen: set[str] = set()
    for job in JOBS[action]:
        if is_cancelled():
            break
        db = os.path.join(profile, job.db)
        if not os.path.isfile(db) or os.path.normcase(db) in seen:
            continue
        seen.add(os.path.normcase(db))
        if job.cookie_column and len(seen) > 1 and action == "chromiumcookies":
            continue  # old "Cookies" path only when the new Network\Cookies file is absent
        try:
            n = _process_db(db, action, job, clean, allowlist, res)
        except sqlite3.Error as e:
            if _is_locked(e):
                res.notes.append(f"{label or 'the browser'} is using {os.path.basename(db)}: close it and run again")
            else:
                res.notes.append(f"{os.path.basename(db)}: {e}")
            continue
        except PermissionError:   # newer Chromium opens Cookies without read sharing while it runs
            res.notes.append(f"{label or 'the browser'} is using {os.path.basename(db)}: close it and run again")
            continue
        except OSError as e:
            res.notes.append(f"{os.path.basename(db)}: {e.strerror or e}")
            continue
        if n:
            res.records += n
            res.items.append((db, n))
    return res


def _process_db(db: str, action: str, job: Job, clean: bool, allowlist: list[str], res: DbResult) -> int:
    if not clean:
        copy = _analyse_copy(db)
        try:
            con = sqlite3.connect(copy)
            try:
                return _count(con, job, allowlist)
            finally:
                con.close()
        finally:
            shutil.rmtree(os.path.dirname(copy), ignore_errors=True)

    before = os.path.getsize(db) + (os.path.getsize(db + "-wal") if os.path.exists(db + "-wal") else 0)
    con = sqlite3.connect(db, timeout=0.5, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")   # fails fast with "database is locked" while the browser runs
        n = _count(con, job, allowlist)
        if n:
            _clean(con, action, job, allowlist)
        con.execute("COMMIT")
        if n:
            con.execute("VACUUM")
            try:
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
    except BaseException:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    after = os.path.getsize(db) + (os.path.getsize(db + "-wal") if os.path.exists(db + "-wal") else 0)
    res.bytes_freed += max(0, before - after)
    return n
