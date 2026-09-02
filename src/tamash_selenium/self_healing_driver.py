"""The one-liner. Wrap your ``WebDriver`` once and every ``find_element`` through it — in Page
Objects, helper/util layers, inside a ``WebDriverWait`` — becomes self-healing. Nothing else
changes.

    from selenium import webdriver
    from tamash_selenium import SelfHealingDriver

    driver = SelfHealingDriver.wrap(webdriver.Chrome())

With no ``.env`` it heals using the rule-based ``tamash`` provider (no key, no network). Set
``HEALER_PROVIDER`` + a key for AI-backed healing. ``HEALER_ENABLED=false`` turns it off entirely.

Wrapping also pins Selenium's implicit wait to 0 — set ``TAMASH_KEEP_IMPLICIT_WAIT=true`` to keep
yours.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from .bindings import bind_driver, unwrap
from .healer.core import get_durable_locator as _get_durable_locator

Locator = Tuple[str, str]


class SelfHealingDriver:
    """Namespace for the wrap entry point (mirrors the Java ``SelfHealingDriver`` static API)."""

    def __new__(cls, *_args: Any, **_kwargs: Any):  # pragma: no cover - guard against instantiation
        raise TypeError("SelfHealingDriver is not instantiable — call SelfHealingDriver.wrap(driver).")

    @staticmethod
    def wrap(driver: Any) -> Any:
        """Wrap ``driver`` so it — and every element found through it — is healing-aware."""
        return bind_driver(driver)


def wrap(driver: Any) -> Any:
    """Function form of :meth:`SelfHealingDriver.wrap`."""
    return bind_driver(driver)


def get_durable(driver: Any, by: Locator, action: Optional[str] = None) -> Locator:
    """Resolve ``by`` to a durable ``(By.*, value)`` equivalent using the same derivation logic
    self-healing uses internally — most useful on a brittle XPath / positional selector. Raises
    if nothing durable could be derived."""
    return _get_durable_locator(unwrap(driver), by, action)
