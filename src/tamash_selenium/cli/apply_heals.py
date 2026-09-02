"""Rewrites healed locators into source, using Python's ``ast`` to target the exact node — no
regex paren-balancing. Handles three shapes:

* inline ``driver.find_element(By.CSS_SELECTOR, "#old")`` -> rewrites the ``By.*, "…"`` args
* a tuple constant ``LOGIN = (By.ID, "old")`` (call site does ``find_element(*LOGIN)``; the heal
  log's ``declarationLocation`` points here) -> rewrites the whole ``(By.*, "…")`` tuple
* a page-object attribute ``self.username = (By.ID, "old")`` -> same as above

Writes ``.tamash-selenium/apply-heals-report.{json,md}`` (+ a timestamped history copy) and a
``verify_heals.py`` that reruns exactly the affected pytest node ids with ``HEALER_ENABLED=false``.
"""

from __future__ import annotations

import ast
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..healer import heal_log
from ..healer.durable_locator import generate_replacement_call
from .console_style import bold, confirm, dim, is_interactive, render_table, section, truncate_end, truncate_start, yellow

_REPORT_DIR = ".tamash-selenium"


# --------------------------------------------------------------------------------------------------
# AST node targeting
# --------------------------------------------------------------------------------------------------


def _line_starts(content: str) -> List[int]:
    starts = [0]
    for line in content.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    return starts


def _char_index(content: str, line_starts: List[int], lineno: int, col_offset: int) -> int:
    line_start = line_starts[lineno - 1]
    line_text = content[line_start:line_starts[lineno]] if lineno < len(line_starts) else content[line_start:]
    prefix = line_text.encode("utf-8")[:col_offset].decode("utf-8", errors="ignore")
    return line_start + len(prefix)


@dataclass
class _Span:
    start: int
    end: int
    full_tuple: bool  # True = replace with "(By.X, \"v\")"; False = replace inner "By.X, \"v\""


def _tuple_span(node: ast.AST, content: str, ls: List[int]) -> Optional[_Span]:
    if isinstance(node, ast.Tuple) and len(node.elts) == 2 and _is_by(node.elts[0]):
        start = _char_index(content, ls, node.lineno, node.col_offset)
        end = _char_index(content, ls, node.end_lineno, node.end_col_offset)
        return _Span(start, end, full_tuple=True)
    return None


def _is_by(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "By":
        return True
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value in ("css selector", "xpath", "id", "name", "class name", "link text",
                              "partial link text", "tag name")
    return False


def _find_span(content: str, target_line: int, is_declaration: bool) -> Optional[_Span]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None
    ls = _line_starts(content)

    if is_declaration:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and getattr(node, "value", None) is not None \
                    and node.value.lineno == target_line:
                span = _tuple_span(node.value, content, ls)
                if span:
                    return span
            if isinstance(node, ast.Assign) and node.lineno == target_line and isinstance(node.value, ast.Tuple):
                span = _tuple_span(node.value, content, ls)
                if span:
                    return span
        return None

    # inline find_element(By.X, "…") on target_line
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr in ("find_element", "find_elements")):
            continue
        if node.lineno != target_line:
            continue
        if len(node.args) >= 2 and _is_by(node.args[0]) and isinstance(node.args[1], ast.Constant):
            start = _char_index(content, ls, node.args[0].lineno, node.args[0].col_offset)
            end = _char_index(content, ls, node.args[1].end_lineno, node.args[1].end_col_offset)
            return _Span(start, end, full_tuple=False)
        # find_element(*LOGIN) — needs the declaration; the caller handles the missing-decl case.
        if len(node.args) == 1 and isinstance(node.args[0], ast.Starred):
            return None
    return None


# --------------------------------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------------------------------


@dataclass
class FixOutcome:
    file: str
    line: int
    before: str
    after: str
    applied: bool
    reason: Optional[str] = None
    needs_review: Optional[bool] = None
    review_note: Optional[str] = None


def _is_better(candidate: dict, current: dict) -> bool:
    cu, ru = bool(candidate.get("suggestion")), bool(current.get("suggestion"))
    if cu != ru:
        return cu
    return candidate.get("timestamp", "") > current.get("timestamp", "")


def _latest_per_location(entries: List[dict]) -> List[dict]:
    by_key: Dict[str, dict] = {}
    for entry in entries:
        key = f"{entry.get('declarationLocation') or (str(entry.get('file')) + ':' + str(entry.get('line')))}"
        existing = by_key.get(key)
        if not existing or _is_better(entry, existing):
            by_key[key] = entry
    return list(by_key.values())


def _target_location(entry: dict) -> Tuple[Optional[str], Optional[int], bool]:
    decl = entry.get("declarationLocation")
    if decl:
        parsed = heal_log.parse_source_location(decl)
        if parsed:
            return parsed[0], parsed[1], True
    return entry.get("file"), entry.get("line"), False


def plan_fixes(cwd: Optional[str] = None, raw_entries: Optional[List[dict]] = None) -> dict:
    cwd = cwd or os.getcwd()
    all_entries = raw_entries if raw_entries is not None else heal_log.read_heal_log(cwd)
    entries = _latest_per_location(all_entries)

    by_file: Dict[str, List[Tuple[dict, int, bool]]] = {}
    for entry in entries:
        if not entry.get("suggestion"):
            continue
        file_name, line, is_decl = _target_location(entry)
        if file_name is None or line is None:
            continue
        by_file.setdefault(file_name, []).append((entry, line, is_decl))

    outcomes: List[FixOutcome] = []
    file_contents: Dict[str, str] = {}

    for relative_file, items in by_file.items():
        full_path = Path(cwd) / relative_file
        if not full_path.exists():
            for entry, line, _ in items:
                outcomes.append(FixOutcome(relative_file, line, "", "", False, "File no longer exists."))
            continue
        content = full_path.read_text(encoding="utf-8")
        changed = False
        for entry, line, is_decl in sorted(items, key=lambda t: t[1], reverse=True):
            replacement = generate_replacement_call(entry["suggestion"])
            span = _find_span(content, line, is_decl) if replacement else None
            if replacement is None:
                outcomes.append(FixOutcome(relative_file, line, "", "", False,
                                           f'Unsupported suggestion strategy "{entry["suggestion"].get("strategy")}".'))
                continue
            if span is None:
                outcomes.append(FixOutcome(relative_file, line, "", "", False,
                                           "Could not locate the original locator on this line — the file may have "
                                           "changed, or the locator is referenced indirectly (a `*name` splat with no "
                                           "recorded declaration). Apply it by hand from heals.jsonl's newLocator."))
                continue
            before = content[span.start:span.end]
            after = replacement if span.full_tuple else replacement[1:-1]  # strip outer parens for inline args
            content = content[:span.start] + after + content[span.end:]
            changed = True
            outcomes.append(FixOutcome(relative_file, line, before, after, True,
                                       needs_review=entry.get("needs_review"), review_note=entry.get("review_note")))
        if changed:
            file_contents[str(full_path)] = content

    applied_locations = {f"{o.file}:{o.line}" for o in outcomes if o.applied}
    affected_tests = sorted({
        entry.get("test_id") for entry in all_entries
        if entry.get("test_id") and f"{entry.get('file')}:{entry.get('line')}" in applied_locations
        or (entry.get("declarationLocation") and entry.get("test_id")
            and f"{heal_log.parse_source_location(entry['declarationLocation'])[0]}:{heal_log.parse_source_location(entry['declarationLocation'])[1]}" in applied_locations)
    })
    return {"outcomes": outcomes, "file_contents": file_contents, "affected_tests": affected_tests}


# --------------------------------------------------------------------------------------------------
# Reports + verify script
# --------------------------------------------------------------------------------------------------


def _timestamp_label() -> str:
    return datetime.now(timezone.utc).isoformat().replace(":", "-").replace(".", "-")


def write_verification_script(affected_tests: List[str], cwd: str) -> Optional[str]:
    if not affected_tests:
        return None
    script_path = Path(cwd) / _REPORT_DIR / "verify_heals.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    content = f'''#!/usr/bin/env python
# Auto-generated by "tamash-selenium apply-heals" — regenerated every run, safe to delete.
# Re-runs exactly the tests affected by the most recent apply-heals run with self-healing disabled.
import os
import subprocess
import sys

os.environ["HEALER_ENABLED"] = "false"
test_args = {affected_tests!r}
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.exit(subprocess.run([sys.executable, "-m", "pytest", *test_args], cwd=project_root).returncode)
'''
    script_path.write_text(content, encoding="utf-8")
    return str(script_path.relative_to(Path(cwd)))


def write_reports(outcomes: List[FixOutcome], affected_tests: List[str], dry_run: bool, cwd: str,
                  label: str, verify_script_path: Optional[str]) -> dict:
    directory = Path(cwd) / _REPORT_DIR
    history_dir = directory / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    applied = [o for o in outcomes if o.applied]
    skipped = [o for o in outcomes if not o.applied]
    timestamp = datetime.now(timezone.utc).isoformat()

    payload = {
        "timestamp": timestamp, "dry_run": dry_run, "applied": len(applied), "skipped": len(skipped),
        "fixes": [asdict(o) for o in outcomes], "affected_tests": affected_tests,
        "verify_script_path": verify_script_path,
        "verify_command": f"python {verify_script_path}" if verify_script_path else None,
    }
    json_content = json.dumps(payload, indent=2)
    (directory / "apply-heals-report.json").write_text(json_content, encoding="utf-8")
    (history_dir / f"{label}.apply-heals-report.json").write_text(json_content, encoding="utf-8")

    lines = ["# Self-healing fixes", "",
             f"Generated {timestamp} by `tamash-selenium apply-heals`"
             f"{' (--dry-run, nothing written)' if dry_run else ''}.", ""]
    if applied:
        review_n = sum(1 for f in applied if f.needs_review)
        lines.append(f"## Applied ({len(applied)}{f', {review_n} needing review' if review_n else ''})\n")
        for fix in applied:
            marker = "⚠️ " if fix.needs_review else ""
            lines += [f"### {marker}`{fix.file}:{fix.line}`", "", "**Before:**", "```python", fix.before, "```",
                      "", "**After:**", "```python", fix.after, "```", ""]
            if fix.needs_review:
                lines += [f"> ⚠️ **Needs review:** {fix.review_note or 'Double-check this selector.'}", ""]
    if skipped:
        lines.append(f"## Skipped ({len(skipped)})\n")
        for fix in skipped:
            lines.append(f"- `{fix.file}:{fix.line}` — {fix.reason}")
        lines.append("")
    if affected_tests:
        lines += ["## Tests to re-verify", "",
                  "Pass these to `pytest` with `HEALER_ENABLED=false` to prove the fixes work standalone:", ""]
        lines += [f"- `{t}`" for t in affected_tests]
        if verify_script_path:
            lines += ["", "```bash", f"python {verify_script_path}", "```", ""]
    markdown = "\n".join(lines)
    (directory / "apply-heals-report.md").write_text(markdown, encoding="utf-8")
    (history_dir / f"{label}.apply-heals-report.md").write_text(markdown, encoding="utf-8")
    return {"json_path": str(directory / "apply-heals-report.json"), "markdown_path": str(directory / "apply-heals-report.md")}


# --------------------------------------------------------------------------------------------------
# CLI entry
# --------------------------------------------------------------------------------------------------


def _print_tables(outcomes: List[FixOutcome], dry_run: bool) -> Tuple[List[FixOutcome], List[FixOutcome]]:
    applied = [o for o in outcomes if o.applied]
    skipped = [o for o in outcomes if not o.applied]
    if applied:
        review_n = sum(1 for o in applied if o.needs_review)
        suffix = f", {review_n} needing review" if review_n else ""
        section(f"Would fix ({len(applied)}{suffix})" if dry_run else f"Fixes ({len(applied)}{suffix})")
        render_table(["Location", "Before", "After", "Review"],
                     [[dim(truncate_start(f"{o.file}:{o.line}", 32)), truncate_end(o.before, 40),
                       truncate_end(o.after, 40), yellow("! yes") if o.needs_review else dim("-")] for o in applied])
        for o in applied:
            if o.needs_review:
                print(f"  {yellow('!')} {dim(f'{o.file}:{o.line}')} - {o.review_note or 'Double-check this selector.'}")
    if skipped:
        section(f"Skipped ({len(skipped)})")
        render_table(["Location", "Reason"],
                     [[dim(truncate_start(f"{o.file}:{o.line}", 32)), truncate_end(o.reason or "", 78)] for o in skipped])
    return applied, skipped


def run_apply_heals(args: Optional[List[str]] = None) -> None:
    args = args or []
    dry_run = "--dry-run" in args
    skip_confirm = "--yes" in args or "-y" in args
    logs_dir = None
    if "--logs-dir" in args:
        i = args.index("--logs-dir")
        logs_dir = args[i + 1] if i + 1 < len(args) else None

    print(bold("tamash-selenium apply-heals"))
    cwd = os.getcwd()
    raw_entries = heal_log.read_heal_logs_from_dir(os.path.join(cwd, logs_dir)) if logs_dir else None
    plan = plan_fixes(cwd, raw_entries)
    outcomes = plan["outcomes"]
    file_contents = plan["file_contents"]
    affected_tests = plan["affected_tests"]

    if not outcomes:
        print(f"No eligible heals found{f' under {logs_dir}' if logs_dir else ' in .tamash-selenium/heals.jsonl'}.")
        print("(Only text-based heals with a known source location are eligible — run your tests first.)")
        return

    applied, skipped = _print_tables(outcomes, dry_run)

    if not dry_run and is_interactive() and not skip_confirm:
        review_n = sum(1 for o in applied if o.needs_review)
        suffix = f" ({review_n} needing review)" if review_n else ""
        if not confirm(f"\nApply {len(applied)} fix(es) to your source files{suffix}? [y/N]: "):
            print("Aborted — no changes written.")
            return

    label = _timestamp_label()
    verify_script_path = write_verification_script(affected_tests, cwd) if not dry_run else None
    reports = write_reports(outcomes, affected_tests, dry_run, cwd, label, verify_script_path)
    print(f"\nReport written to {os.path.relpath(reports['markdown_path'], cwd)} (and the matching .json).")

    if dry_run:
        print(f"{len(applied)} fix(es) would be applied, {len(skipped)} skipped. Re-run without --dry-run to write them.")
        return

    for full_path, content in file_contents.items():
        Path(full_path).write_text(content, encoding="utf-8")
    print(f"{len(applied)} fix(es) applied to {len(file_contents)} file(s), {len(skipped)} skipped.")
    print("Review the changes (e.g. `git diff`) before committing.")
    if verify_script_path:
        print(f"Verification script: python {verify_script_path}")

    if logs_dir:
        heal_log.archive_merged_entries(raw_entries or [], label, cwd)
    else:
        heal_log.archive_heal_log(label, cwd)
    heal_log.clear_heal_log(cwd)
