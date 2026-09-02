"""Backs ``tamash-selenium init-skill`` (copies the bundled coding-agent skill into a project)
and ``doctor``'s Skill check.

Follows the convention Playwright's ``playwright-cli install --skills`` established: the same
``SKILL.md`` + ``references/`` goes into **both** standard locations —

  ``.claude/skills/tamash-selenium/``  — Claude Code
  ``.agents/skills/tamash-selenium/``  — the cross-tool standard (Cursor, Copilot, Windsurf, …)

A one-line version marker (``.tamash-selenium-skill``) records the package version so ``doctor``
can flag a stale copy.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

_MARKER_FILENAME = ".tamash-selenium-skill"
_MARKER_PREFIX = "tamash-selenium-skill-version:"
_MARKER_RE = re.compile(r"tamash-selenium-skill-version:\s*(\S+)")

_SKILL_SRC = Path(__file__).resolve().parent.parent / "skills" / "tamash-selenium"
_SKILL_FILES = ["SKILL.md", "references/onboarding.md", "references/heal.md"]


@dataclass(frozen=True)
class TargetSpec:
    id: str
    label: str
    project_dir: Path
    user_dir: Path


TARGETS: List[TargetSpec] = [
    TargetSpec("claude", "Claude Code (.claude/skills/)",
               Path(".claude/skills/tamash-selenium"),
               Path.home() / ".claude/skills/tamash-selenium"),
    TargetSpec("agents", "cross-tool standard (.agents/skills/)",
               Path(".agents/skills/tamash-selenium"),
               Path.home() / ".agents/skills/tamash-selenium"),
]


def get_target(target_id: str) -> Optional[TargetSpec]:
    return next((t for t in TARGETS if t.id == target_id), None)


def get_package_version() -> str:
    try:
        from importlib.metadata import version
        return version("tamash-selenium")
    except Exception:  # noqa: BLE001
        try:
            from .. import __version__
            return __version__
        except Exception:  # noqa: BLE001
            return "unknown"


def version_marker(version: str) -> str:
    return f"{_MARKER_PREFIX} {version}"


def read_version_marker(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = _MARKER_RE.search(text)
    return m.group(1) if m else None


def skill_resource_available() -> bool:
    return (_SKILL_SRC / "SKILL.md").is_file()


def skill_state(cwd: str, target: TargetSpec, package_version: str) -> dict:
    directory = Path(cwd) / target.project_dir
    if not (directory / "SKILL.md").exists():
        return {"status": "absent"}
    marker = directory / _MARKER_FILENAME
    if not marker.exists():
        return {"status": "unmanaged"}
    try:
        installed = read_version_marker(marker.read_text(encoding="utf-8"))
    except OSError:
        return {"status": "unmanaged"}
    if installed is None:
        return {"status": "unmanaged"}
    if installed == package_version:
        return {"status": "current", "version": installed}
    return {"status": "outdated", "installed": installed, "version": package_version}


def legacy_install_artifacts(cwd: str) -> List[str]:
    out: List[str] = []
    for legacy in (".claude/skills/tamash_selenium", ".agents/skills/tamash_selenium"):
        if (Path(cwd) / legacy).exists():
            out.append(legacy)
    return out


def install_skill(target: TargetSpec, cwd: Path, version: str, user: bool = False,
                  force: bool = False, dry_run: bool = False) -> dict:
    dest = target.user_dir if user else cwd / target.project_dir
    existed = (dest / "SKILL.md").exists()
    managed = (dest / _MARKER_FILENAME).exists()

    if existed and not managed and not force:
        return {"target": target, "action": "blocked", "path": str(dest),
                "detail": "a skill directory exists here with no version marker (hand-customized?) — re-run with --force"}
    if existed and managed and not force:
        try:
            installed = read_version_marker((dest / _MARKER_FILENAME).read_text(encoding="utf-8"))
            if installed == version:
                return {"target": target, "action": "skipped", "path": str(dest), "detail": "already up to date"}
        except OSError:
            pass

    if dry_run:
        return {"target": target, "action": "updated" if existed else "created", "path": str(dest),
                "detail": "(dry run — nothing written)"}

    if not skill_resource_available():
        return {"target": target, "action": "blocked", "path": str(dest),
                "detail": "the bundled skill files are missing from this install"}

    for rel in _SKILL_FILES:
        src = _SKILL_SRC / rel
        if not src.exists():
            continue
        target_file = dest / rel
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target_file)
    (dest / _MARKER_FILENAME).write_text(version_marker(version) + "\n", encoding="utf-8")
    return {"target": target, "action": "updated" if existed else "created", "path": str(dest), "detail": None}


def run_init_skill(args: Optional[List[str]] = None) -> None:
    args = args or []
    from .console_style import bold, dim, green, yellow

    only = None
    if "--target" in args:
        i = args.index("--target")
        only = args[i + 1] if i + 1 < len(args) else None
    user = "--user" in args
    force = "--force" in args
    dry_run = "--dry-run" in args

    print(bold("tamash-selenium init-skill"))
    version = get_package_version()
    cwd = Path(os.getcwd())
    targets = [t for t in TARGETS if only is None or t.id == only]
    if not targets:
        print(f"Unknown --target {only!r} (expected: claude | agents)")
        return

    for target in targets:
        result = install_skill(target, cwd, version, user=user, force=force, dry_run=dry_run)
        action = result["action"]
        colour = {"created": green, "updated": green, "skipped": dim, "blocked": yellow}.get(action, dim)
        detail = f" — {result['detail']}" if result.get("detail") else ""
        print(f"  {colour(action)}  {result['path']}{detail}")

    print(dim(f"\nSkill version: {version}. Re-run this command to refresh after upgrading the package."))
