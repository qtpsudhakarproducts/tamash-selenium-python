"""tamash-selenium — plug-and-play self-healing for Selenium + Python.

    from selenium import webdriver
    from tamash_selenium import SelfHealingDriver

    driver = SelfHealingDriver.wrap(webdriver.Chrome())
    driver.get("https://example.com/login")
    driver.find_element(By.ID, "username").send_keys("admin")   # healed automatically if it breaks

See ``README.md`` for the framework integrations (pytest / pytest-bdd / Behave / unittest) and
the ``HEALER_*`` environment variables.
"""

from __future__ import annotations

from .bindings import bind_driver, bind_element, unwrap
from .healer import SelfHealingReport, get_healing_reports, heal_action_failure
from .self_healing_driver import SelfHealingDriver, get_durable, wrap
from .tamash import clear_hint, current_hint, hint, set_hint

__version__ = "0.1.0"

__all__ = [
    "SelfHealingDriver",
    "wrap",
    "get_durable",
    "bind_driver",
    "bind_element",
    "unwrap",
    "hint",
    "set_hint",
    "clear_hint",
    "current_hint",
    "heal_action_failure",
    "get_healing_reports",
    "SelfHealingReport",
    "__version__",
]
