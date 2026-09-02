"""An append-only JSONL trail of eligible heals under ``.tamash-selenium/heals.jsonl`` — reused as
an in-run / cross-run cache and consumed by ``tamash-selenium apply-heals``. Every method is
best-effort: a logging failure must never break a test run.

Port of ``tamash-playwright-python``'s ``heal_log.py`` (directory renamed) with the Java port's
extra ``declaration_location`` / ``new_locator`` fields.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

_LOG_DIR = ".tamash-selenium"
_LOG_FILE = "heals.jsonl"


def _log_path(cwd: str) -> Path:
    return Path(cwd) / _LOG_DIR / _LOG_FILE


def parse_source_location(source_location: Optional[str]) -> Optional[Tuple[str, int]]:
    if not source_location:
        return None
    sep = source_location.rfind(":")
    if sep == -1:
        return None
    try:
        return source_location[:sep], int(source_location[sep + 1 :])
    except ValueError:
        return None


def append_heal_log_entry(entry: dict, cwd: Optional[str] = None) -> None:
    cwd = cwd or os.getcwd()
    try:
        directory = Path(cwd) / _LOG_DIR
        directory.mkdir(parents=True, exist_ok=True)
        with open(_log_path(cwd), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def _parse_heal_log_file(file_path: Path) -> List[dict]:
    if not file_path.exists():
        return []
    entries: List[dict] = []
    for line in file_path.read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def read_heal_log(cwd: Optional[str] = None) -> List[dict]:
    return _parse_heal_log_file(_log_path(cwd or os.getcwd()))


def read_heal_logs_from_dir(directory: str) -> List[dict]:
    root = Path(directory)
    if not root.exists():
        return []
    entries: List[dict] = []
    for path in root.rglob(_LOG_FILE):
        entries.extend(_parse_heal_log_file(path))
    return entries


def find_cached_suggestion(source_location: str, cwd: Optional[str] = None) -> Optional[dict]:
    location = parse_source_location(source_location)
    if location is None:
        return None
    file_name, line = location

    newest: Optional[dict] = None
    for entry in read_heal_log(cwd):
        suggestion = entry.get("suggestion")
        if entry.get("file") != file_name or entry.get("line") != line or not suggestion:
            continue
        if newest is None or entry.get("timestamp", "") > newest.get("timestamp", ""):
            newest = entry
    if newest is None:
        return None
    return {
        "suggestion": newest.get("suggestion"),
        "initial_selector": newest.get("initial_selector"),
        "needs_review": newest.get("needs_review"),
        "review_note": newest.get("review_note"),
    }


def archive_heal_log(label: str, cwd: Optional[str] = None) -> None:
    cwd = cwd or os.getcwd()
    try:
        src = _log_path(cwd)
        if not src.exists():
            return
        history_dir = Path(cwd) / _LOG_DIR / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, history_dir / f"{label}.heals.jsonl")
    except OSError:
        pass


def archive_merged_entries(entries: List[dict], label: str, cwd: Optional[str] = None) -> None:
    if not entries:
        return
    cwd = cwd or os.getcwd()
    try:
        history_dir = Path(cwd) / _LOG_DIR / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        content = "\n".join(json.dumps(entry) for entry in entries) + "\n"
        (history_dir / f"{label}.heals.jsonl").write_text(content, encoding="utf-8")
    except OSError:
        pass


def clear_heal_log(cwd: Optional[str] = None) -> None:
    cwd = cwd or os.getcwd()
    try:
        _log_path(cwd).unlink(missing_ok=True)
    except OSError:
        pass
