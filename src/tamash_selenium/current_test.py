"""A context-local carrying which test is currently running, so the healer can record WHICH test
exercised a healed location (``apply-heals`` re-verifies exactly those tests).

Set by every framework integration (pytest plugin, Behave hooks, unittest base class) in its
per-test setup and cleared in teardown. The value handed to the test runner is the framework's
own addressable id — a pytest nodeid, ``Class.method`` for unittest, ``feature::scenario`` for BDD.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TestInfo:
    test_id: str
    title: Optional[str] = None


_CURRENT: contextvars.ContextVar[Optional[TestInfo]] = contextvars.ContextVar(
    "tamash_current_test", default=None
)


def set_current(info: Optional[TestInfo]) -> None:
    _CURRENT.set(info)


def clear() -> None:
    _CURRENT.set(None)


def get() -> Optional[TestInfo]:
    return _CURRENT.get()


def current_test_id() -> Optional[str]:
    info = _CURRENT.get()
    return info.test_id if info else None
