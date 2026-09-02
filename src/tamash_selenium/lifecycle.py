"""Browser launch -> per-test scope lifecycle, shared by every framework integration (the pytest
``driver`` fixture, ``TamashSeleniumTestCase``, the Behave / pytest-bdd hooks) so all behave
identically.

Port of the Java ``SeleniumLifecycle``. A fresh ``WebDriver`` per test by default;
``TAMASH_REUSE_DRIVER=true`` reuses one per test class / feature (cookies + storage cleared
between tests). Selenium's implicit wait is pinned to 0 by :func:`tamash_selenium.wrap`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from . import env
from .self_healing_driver import wrap


@dataclass
class Scope:
    raw_driver: Any
    driver: Any  # the healing-wrapped view the test uses
    owned: bool  # True = teardown quits it; False = reused, teardown just resets


def reuse_driver() -> bool:
    return env.get_bool("TAMASH_REUSE_DRIVER", False)


def is_headless() -> bool:
    value = env.get("HEADLESS")
    return value is None or value.strip().lower() != "false"


def new_driver() -> Any:
    browser = (env.get("TAMASH_BROWSER") or "chrome").strip().lower()
    headless = is_headless()

    from selenium import webdriver

    if browser == "firefox":
        options = webdriver.FirefoxOptions()
        if headless:
            options.add_argument("-headless")
        return webdriver.Firefox(options=options)
    if browser == "edge":
        options = webdriver.EdgeOptions()
        if headless:
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
        return webdriver.Edge(options=options)
    if browser == "safari":  # macOS only; HEADLESS ignored
        return webdriver.Safari()

    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    return webdriver.Chrome(options=options)


def _reset_for_reuse(driver: Any) -> None:
    try:
        driver.get("about:blank")
        driver.delete_all_cookies()
        driver.execute_script("try { localStorage.clear(); sessionStorage.clear(); } catch (e) {}")
    except Exception:  # noqa: BLE001
        pass


def _quiet_quit(driver: Any) -> None:
    try:
        driver.quit()
    except Exception:  # noqa: BLE001
        pass


class SeleniumSession:
    """Held for the whole test class / feature. Holds a driver only when ``TAMASH_REUSE_DRIVER=true``."""

    def __init__(self) -> None:
        self._class_driver: Optional[Any] = new_driver() if reuse_driver() else None

    def open_scope(self) -> Scope:
        reuse = reuse_driver()
        raw = self._class_driver if (reuse and self._class_driver is not None) else new_driver()
        if reuse:
            _reset_for_reuse(raw)
        return Scope(raw_driver=raw, driver=wrap(raw), owned=not reuse)

    def close_scope(self, scope: Optional[Scope]) -> None:
        if scope is not None and scope.owned:
            _quiet_quit(scope.raw_driver)

    def close(self) -> None:
        if self._class_driver is not None:
            _quiet_quit(self._class_driver)
