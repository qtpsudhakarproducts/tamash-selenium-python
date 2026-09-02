"""In-memory, per-run heal cache — what makes healing *inside* a ``WebDriverWait`` affordable. A
wait polls ``find_element`` many times; without this, each poll would trigger a fresh snapshot +
provider call.

* **Positive**: once ``(broken_locator, page)`` has healed this run, every later failure for that
  locator — including the wait's next poll and any other caller — reuses the healed locator
  instantly. Kept for the whole run.
* **Negative**: if a heal was just attempted and *declined* for the current DOM state, don't retry
  until the DOM changes. A genuine "not there yet" then lets the wait poll normally.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

Locator = Tuple[str, str]

_NEGATIVE_TTL_S = 3.0

_lock = threading.Lock()
_positive: Dict[str, "Hit"] = {}
_negative: Dict[str, float] = {}
_fail_count: Dict[str, int] = {}
_healed_locators: set = set()


@dataclass(frozen=True)
class Hit:
    healed_locator: Locator
    described_as: Optional[str]
    suggestion: Optional[dict]


def _key(locator: Optional[Locator]) -> str:
    return "" if locator is None else str(tuple(locator))


def record_failing(broken: Optional[Locator]) -> int:
    if broken is None:
        return 99
    with _lock:
        key = _key(broken)
        _fail_count[key] = _fail_count.get(key, 0) + 1
        return _fail_count[key]


def fail_count(broken: Optional[Locator]) -> int:
    if broken is None:
        return 0
    with _lock:
        return _fail_count.get(_key(broken), 0)


def positive(broken: Optional[Locator], page_key: Optional[str]) -> Optional[Hit]:
    if broken is None:
        return None
    with _lock:
        return _positive.get(f"{_key(broken)}@{page_key or ''}")


def record_positive(broken: Locator, page_key: Optional[str], healed: Locator,
                    described_as: Optional[str], suggestion: Optional[dict]) -> None:
    with _lock:
        _positive[f"{_key(broken)}@{page_key or ''}"] = Hit(healed, described_as, suggestion)
        _healed_locators.add(_key(broken))


def ever_healed(broken: Optional[Locator]) -> bool:
    if broken is None:
        return False
    with _lock:
        return _key(broken) in _healed_locators


def recently_declined(broken: Optional[Locator], dom_key: Optional[str]) -> bool:
    if broken is None:
        return False
    with _lock:
        ts = _negative.get(f"{_key(broken)}#{dom_key or ''}")
    return ts is not None and (time.time() - ts) < _NEGATIVE_TTL_S


def record_declined(broken: Optional[Locator], dom_key: Optional[str]) -> None:
    if broken is None:
        return
    with _lock:
        _negative[f"{_key(broken)}#{dom_key or ''}"] = time.time()


def clear() -> None:
    """Cleared per test by the framework integrations to bound cross-test bleed; left alone in the
    plain plug-and-play case."""
    with _lock:
        _positive.clear()
        _negative.clear()
        _fail_count.clear()
        _healed_locators.clear()
