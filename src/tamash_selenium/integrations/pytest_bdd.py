"""pytest-bdd integration.

pytest-bdd scenarios run as ordinary pytest tests, so the ``tamash_selenium`` pytest plugin
already covers them — per-scenario heal attribution, the HTML step report, and the
``tamash_driver`` / ``driver`` fixtures all work from step functions with no extra wiring::

    from pytest_bdd import scenarios, given, when, then
    from selenium.webdriver.common.by import By

    scenarios("../features/login.feature")

    @when("I sign in as \"admin\"")
    def _(tamash_driver):
        tamash_driver.find_element(By.ID, "username").send_keys("admin")   # healed if it breaks

This module re-exports the fixtures for an explicit import and provides
:func:`tamash_selenium_driver` as an alias some suites prefer.
"""

from __future__ import annotations

from .pytest_plugin import driver, tamash_driver  # noqa: F401  (re-exported as pytest fixtures)

tamash_selenium_driver = tamash_driver

__all__ = ["driver", "tamash_driver", "tamash_selenium_driver"]
