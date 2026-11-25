"""CSV rows and read-only reports for the desktop tools."""
import csv
import os
import stat
from collections import Counter
from pathlib import Path


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        for row in rows:
            writer.writerow(["'" + cell if isinstance(cell, str) and cell.startswith(("=", "+", "-", "@", "\t", "\r"))
                             else cell for cell in row])


def clean_rows(results):
    yield ("Rule", "Mode", "Entry", "Item", "Files", "Bytes", "Records", "Registry items", "Errors")
    for r in results:
        yield (r.rule_id, r.mode, "Summary", r.name, r.files, r.bytes, r.records, r.reg_items, len(r.errors))
        for path, size in r.items:
            yield (r.rule_id, r.mode, "Detail", path, "", size, "", "", "")
        for error in r.errors:
            yield (r.rule_id, r.mode, "Error", error, "", "", "", "", "")


def disk_usage(root, cancel, on_skip=None):
    sizes, counts = Counter(), Counter()
    pending = [root]
    skipped = 0

    def skip(path, reason):
        nonlocal skipped
        skipped += 1
        if on_skip is not None:
            on_skip(str(path), reason)

    while pending and not cancel.is_set():
        directory = pending.pop()
        try:
            st = os.lstat(directory)
            if stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & 0x400:
                skip(directory, "Link or reparse point")
                continue
            with os.scandir(directory) as entries:
                for entry in entries:
                    if cancel.is_set():
                        break
                    try:
                        st = entry.stat(follow_symlinks=False)
                        if stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & (0x400 | 0x40000 | 0x400000):
                            skip(entry.path, "Link or cloud placeholder")
                        elif stat.S_ISDIR(st.st_mode):
                            pending.append(entry.path)
                        elif stat.S_ISREG(st.st_mode):
                            kind = Path(entry.name).suffix.lower() or "(no extension)"
                            sizes[kind] += st.st_size
                            counts[kind] += 1
                    except OSError as error:
                        skip(entry.path, str(error))
        except OSError as error:
            skip(directory, str(error))
    return sizes, counts, skipped


def activity_totals(history):
    days = {}
    for row in history:
        day = row["time"].split(" ")[0]
        counts = days.setdefault(day, Counter())
        if row.get("mode", "clean") == "clean":
            counts["cleans"] += 1
            counts["freed"] += row.get("freed", 0)
        else:
            counts["scans"] += 1
        counts["errors"] += row.get("errors", 0)
    return days
