"""Parser for the CCleaner-style cleaning-rule INI format.

Format observed in CCleaner 7's ccleaner.ini (see docs/HOW_CCLEANER_WORKS.md):

    [Rule Vars]                      ; NAME=comma,separated,paths  -> used as <NAME>
    [Rule display name]
    ID=windows.tempfiles
    Default=True
    DetectOS=6.0                     ; minimum Windows NT version
    Detect=HKCU\\Software\\X         ; registry key must exist
    DetectFile1=<VAR>\\Sub           ; any path must exist
    ActiveProcesses=chrome.exe;...   ; warn if running
    FileKey1=<dir>|<pat;pat>|FLAGS   ; FLAGS: RECURSE, REMOVESELF
    RegKey1=HKCU\\path[|ValueName]
    ExcludeKey1=FILE|<path> / PATH|<dir>
    OnFile1=<pattern>|FileDelete | FileDeleteIfOlderThan|<N>days|hours
    Action1=EmptyRecycleBin          ; built-in handler, optional |arg
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileKey:
    path: str
    patterns: list[str]
    recurse: bool = False
    remove_self: bool = False


@dataclass
class RegKey:
    path: str
    value: str | None = None


@dataclass
class Exclude:
    kind: str  # FILE | PATH
    path: str


@dataclass
class OnFile:
    pattern: str
    handler: str
    arg: str | None = None


@dataclass
class Action:
    name: str
    arg: str | None = None


@dataclass
class Rule:
    name: str
    id: str = ""
    group: str = "Other"
    default: bool = False
    detect_os: tuple[int, int] | None = None
    detect: list[str] = field(default_factory=list)
    detect_files: list[str] = field(default_factory=list)
    active_processes: list[str] = field(default_factory=list)
    warning: str = ""
    file_keys: list[FileKey] = field(default_factory=list)
    reg_keys: list[RegKey] = field(default_factory=list)
    excludes: list[Exclude] = field(default_factory=list)
    on_file: list[OnFile] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    needs_admin: bool = False


@dataclass
class RuleSet:
    vars: dict[str, list[str]] = field(default_factory=dict)
    rules: list[Rule] = field(default_factory=list)

    def by_id(self) -> dict[str, Rule]:
        return {r.id: r for r in self.rules}


_NUM_SUFFIX = re.compile(r"^([A-Za-z]+?)\d*$")


def _split_sections(text: str):
    section = None
    items: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in ";#":
            continue
        if line.startswith("[") and line.endswith("]"):
            if section is not None:
                yield section, items
            section, items = line[1:-1], []
        elif "=" in line and section is not None:
            k, v = line.split("=", 1)
            items.append((k.strip(), v.strip()))
    if section is not None:
        yield section, items


def _parse_filekey(value: str) -> FileKey:
    parts = value.split("|")
    path = parts[0].strip()
    patterns = [p.strip() for p in (parts[1] if len(parts) > 1 else "*").split(";") if p.strip()]
    flags = {f.strip().upper() for f in parts[2:]} if len(parts) > 2 else set()
    return FileKey(path, patterns or ["*"], "RECURSE" in flags, "REMOVESELF" in flags)


def _parse_regkey(value: str) -> RegKey:
    path, _, val = value.partition("|")
    return RegKey(path.strip(), val.strip() or None)


def _parse_version(text: str) -> tuple[int, int] | None:
    m = re.match(r"(\d+)\.(\d+)", text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def parse_rules(text: str) -> RuleSet:
    rs = RuleSet()
    for name, items in _split_sections(text):
        if name.lower() == "rule vars":
            for k, v in items:
                rs.vars[k.upper()] = [p.strip() for p in v.split(",") if p.strip()]
            continue
        rule = Rule(name=name)
        for key, value in items:
            base = _NUM_SUFFIX.match(key).group(1).lower()
            if base == "id":
                rule.id = value
            elif base == "group":
                rule.group = value
            elif base == "default":
                rule.default = value.lower() == "true"
            elif base == "detectos":
                rule.detect_os = _parse_version(value)
            elif base == "detect":
                rule.detect.append(value)
            elif base == "detectfile":
                rule.detect_files.append(value)
            elif base == "activeprocesses":
                rule.active_processes += [p.strip() for p in re.split(r"[;|]", value) if p.strip()]
            elif base == "warning":
                rule.warning = value
            elif base == "filekey":
                rule.file_keys.append(_parse_filekey(value))
            elif base == "regkey":
                rule.reg_keys.append(_parse_regkey(value))
            elif base == "excludekey":
                kind, _, rest = value.partition("|")
                rule.excludes.append(Exclude(kind.upper(), rest.split("|")[0]))
            elif base == "onfile":
                p = value.split("|")
                if len(p) >= 2:
                    rule.on_file.append(OnFile(p[0], p[1], p[2] if len(p) > 2 else None))
            elif base == "action":
                name_, _, arg = value.partition("|")
                rule.actions.append(Action(name_.strip(), arg.strip() or None))
            elif base == "needsadmin":
                rule.needs_admin = value.lower() == "true"
        if not rule.id:
            rule.id = re.sub(r"[^a-z0-9]+", ".", name.lower()).strip(".")
        rs.rules.append(rule)
    return rs


def load_rules(path: str | Path) -> RuleSet:
    return parse_rules(Path(path).read_text(encoding="utf-8-sig"))
