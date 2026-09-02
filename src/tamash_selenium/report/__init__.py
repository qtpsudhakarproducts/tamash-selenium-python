"""HTML step report.

Enabled by ``--tamash-report <path>`` (pytest) or ``TAMASH_REPORT=<path>`` (env, for plain
scripts / Behave / unittest). Every intercepted action, and every heal, is recorded as a step;
at the end of the run the collected steps render to a single self-contained HTML file. Zero
overhead when neither is set — :func:`record_step` returns immediately.
"""

from __future__ import annotations

import atexit
import contextvars
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import env

_enabled = False
_store_dir: Optional[Path] = None
_output_path: Optional[Path] = None
_atexit_registered = False

_SESSION_BUCKET = "(session)"

_current_test_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "tamash_report_current_test", default=None
)
_suppressed: contextvars.ContextVar[bool] = contextvars.ContextVar("tamash_report_suppressed", default=False)

_steps_by_test: Dict[str, List[dict]] = {}
_phase_durations_by_test: Dict[str, Dict[str, float]] = {}
_status_by_test: Dict[str, str] = {}


class suppress:
    """Context manager the healer wraps its internal replays in so they don't record a
    duplicate step (the outer failing action already records the healed one)."""

    def __enter__(self) -> None:
        self._token = _suppressed.set(True)

    def __exit__(self, *_exc: Any) -> None:
        _suppressed.reset(self._token)


def is_report_enabled() -> bool:
    return _enabled


def is_suppressed() -> bool:
    return _suppressed.get()


def enable(store_dir: Optional[Path] = None, output_path: Optional[Path] = None) -> None:
    global _enabled, _store_dir, _output_path
    _enabled = True
    _store_dir = store_dir or Path(tempfile.mkdtemp(prefix="tamash-report-"))
    if output_path is not None:
        _output_path = Path(output_path)


def enable_from_env() -> None:
    """Called from ``bind_driver`` — turns the report on when ``TAMASH_REPORT`` is set and no
    framework plugin already enabled it. Registers an ``atexit`` flush for the plain path."""
    global _atexit_registered
    if _enabled:
        return
    target = env.get("TAMASH_REPORT")
    if not target:
        return
    enable(output_path=Path(target))
    if not _atexit_registered:
        _atexit_registered = True
        atexit.register(_finalize_session)


def _finalize_session() -> None:
    for bucket in list(_steps_by_test.keys()):
        flush_test(bucket, _status_by_test.get(bucket, "passed"))
    write_report_if_configured()


def set_current_test(test_id: Optional[str]) -> None:
    _current_test_id.set(test_id)


def get_current_test_id() -> Optional[str]:
    return _current_test_id.get()


def record_step(*, category: str = "action", action: str, element: Optional[str] = None,
                locator: Optional[str] = None, value: Optional[str] = None, duration_ms: float = 0.0,
                healed: bool = False, error: Optional[str] = None, suggested_selector: Optional[str] = None,
                provider: Optional[str] = None, token_usage: Optional[dict] = None,
                failure_stage: Optional[str] = None, used_action_recovery: bool = False,
                needs_review: Optional[bool] = None, review_note: Optional[str] = None,
                aria_snapshot: Optional[str] = None, test_id: Optional[str] = None) -> None:
    if not _enabled or _suppressed.get():
        return
    key = test_id if test_id is not None else (_current_test_id.get() or _SESSION_BUCKET)
    _steps_by_test.setdefault(key, []).append({
        "category": category, "action": action, "element": element or action, "locator": locator,
        "value": value, "duration_ms": duration_ms, "healed": healed, "error": error,
        "suggested_selector": suggested_selector, "provider": provider, "failure_stage": failure_stage,
        "token_usage": dict(token_usage) if token_usage else None,
        "used_action_recovery": used_action_recovery, "needs_review": needs_review,
        "review_note": review_note, "aria_snapshot": aria_snapshot,
    })


def record_phase_duration(nodeid: str, phase: str, duration_ms: float) -> None:
    if _enabled:
        _phase_durations_by_test.setdefault(nodeid, {})[phase] = duration_ms


def set_test_status(nodeid: str, status: str) -> None:
    if _enabled:
        _status_by_test[nodeid] = status


def get_test_status(nodeid: str) -> Optional[str]:
    return _status_by_test.get(nodeid)


def _sanitize(nodeid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", nodeid)


def flush_test(nodeid: str, status: str) -> None:
    if not _enabled or _store_dir is None:
        return
    steps = _steps_by_test.pop(nodeid, [])
    phase_durations = _phase_durations_by_test.pop(nodeid, {})
    _status_by_test.pop(nodeid, None)
    duration_ms = sum(phase_durations.values()) or sum(s["duration_ms"] for s in steps)
    _store_dir.mkdir(parents=True, exist_ok=True)
    (_store_dir / f"{_sanitize(nodeid)}.json").write_text(json.dumps({
        "nodeid": nodeid, "status": status, "duration_ms": duration_ms,
        "phase_durations": phase_durations, "steps": steps,
    }), encoding="utf-8")


def aggregate(store_dir: Optional[Path] = None) -> List[dict]:
    directory = store_dir or _store_dir
    if directory is None or not directory.exists():
        return []
    tests = []
    for path in sorted(directory.glob("*.json")):
        try:
            tests.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return tests


def cleanup(store_dir: Optional[Path] = None) -> None:
    directory = store_dir or _store_dir
    if directory is not None:
        shutil.rmtree(directory, ignore_errors=True)


def write_report_if_configured() -> None:
    if not _enabled or _output_path is None:
        return
    from .render import render
    tests = aggregate()
    if not tests:
        return
    _output_path.parent.mkdir(parents=True, exist_ok=True)
    _output_path.write_text(render(tests), encoding="utf-8")
    print(f"[tamash] step report written to {_output_path}")
    cleanup()


def reset() -> None:
    """Test hook."""
    global _enabled, _store_dir, _output_path, _atexit_registered
    _enabled = False
    _store_dir = None
    _output_path = None
    _atexit_registered = False
    _steps_by_test.clear()
    _phase_durations_by_test.clear()
    _status_by_test.clear()
