"""The Selenium stand-in for Playwright's ``aria_snapshot(mode="ai")``. A single injected script
(:mod:`dom_snapshot.js`) walks the live DOM and emits a YAML accessibility tree in the exact shape
:func:`tamash_selenium.healer.durable_locator.parse_aria_ai_tree` parses.

Every emitted element is stamped ``data-tamash-ref="eN"`` so an AI-picked ``[ref=eN]`` resolves to a
real node via ``(By.CSS_SELECTOR, "[data-tamash-ref='eN']")``.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from .. import env

_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dom_snapshot.js")

try:
    with open(_SCRIPT_PATH, "r", encoding="utf-8") as _handle:
        # The file is an IIFE; execute_script needs a top-level `return` to see its value.
        _CAPTURE_JS: Optional[str] = "return " + _handle.read()
except OSError:  # pragma: no cover - defensive
    _CAPTURE_JS = None

_CLEAR_JS = (
    "document.querySelectorAll('[data-tamash-ref]')"
    ".forEach(function(e){e.removeAttribute('data-tamash-ref');});"
)

REF_ATTRIBUTE = "data-tamash-ref"


def _debug(message: str) -> None:
    if env.get("TAMASH_DEBUG"):
        print(f"[tamash-debug] {message}")


def capture(driver: Any) -> Optional[str]:
    """Capture the accessibility tree for the driver's current document / active frame. Returns
    ``None`` if the script fails (the healer then falls through to ``failure_stage=no_snapshot``)."""
    if _CAPTURE_JS is None or driver is None:
        return None
    try:
        result = driver.execute_script(_CAPTURE_JS)
        yaml = str(result) if result is not None else None
        _debug(f"snapshot len={len(yaml) if yaml else 'None'}")
        return yaml if yaml and yaml.strip() else None
    except Exception as exc:  # noqa: BLE001 - best-effort diagnostic capture
        _debug(f"snapshot failed: {exc}")
        return None


def clear_refs(driver: Any) -> None:
    """Best-effort — the healed action may already have navigated away or replaced the nodes."""
    try:
        driver.execute_script(_CLEAR_JS)
    except Exception:  # noqa: BLE001
        pass
