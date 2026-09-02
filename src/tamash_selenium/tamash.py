"""The explicit description hook — for when the automatic call-site decode isn't enough
(keyword-driven suites, opaque locator names like ``txt_ssn``, heavy wrapper indirection).

Recommended (auto-clears on scope exit)::

    from tamash_selenium import hint

    def click(locator, name):
        with hint(name):
            driver.find_element(*locator).click()

Bare form also works — overwritten by the next :func:`hint` and cleared per test by the framework
integrations::

    hint("Username field")
    driver.find_element(By.ID, "old").send_keys("admin")

The hint takes precedence over the decoded variable / field name and is passed to the AI provider
as the element's name. It has no effect on whether a heal is *attempted* (assert-absent /
``HEALER_ASSERTIONS=strict`` still apply).
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Iterator, Optional

_HINT: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("tamash_hint", default=None)


@contextmanager
def hint(description: Optional[str]) -> Iterator[None]:
    """Set the healer's element description for the duration of the ``with`` block."""
    normalized = description.strip() if description and description.strip() else None
    token = _HINT.set(normalized)
    try:
        yield
    finally:
        _HINT.reset(token)


def set_hint(description: Optional[str]) -> None:
    """Bare setter — persists until the next :func:`set_hint` / :func:`clear_hint`."""
    _HINT.set(description.strip() if description and description.strip() else None)


def clear_hint() -> None:
    _HINT.set(None)


def current_hint() -> Optional[str]:
    """The active hint for this context, or ``None``. Read by the healer."""
    return _HINT.get()
