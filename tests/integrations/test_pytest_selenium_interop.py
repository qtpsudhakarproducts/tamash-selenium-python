"""When a project already uses ``pytest-selenium`` (which provides its own ``driver`` fixture from
a conftest), that fixture wins over the ``tamash_selenium`` plugin's — so wrapping is the project's
one line: ``driver = SelfHealingDriver.wrap(driver)``. This test proves the two plugins coexist
(no fixture-name crash on collection) and the wrapped pytest-selenium driver heals.
"""

from __future__ import annotations

import importlib.util

import pytest
from selenium.webdriver.common.by import By

pytestmark = pytest.mark.e2e

_HAS_PYTEST_SELENIUM = importlib.util.find_spec("pytest_selenium") is not None

_PAGE = (
    "data:text/html,<form><label for='u'>Username</label>"
    "<input id='u' name='username'><button id='go' type='button' "
    "onclick=\"document.getElementById('o').textContent=document.getElementById('u').value\">Go</button>"
    "<div id='o'></div></form>"
)


@pytest.mark.skipif(not _HAS_PYTEST_SELENIUM, reason="pytest-selenium not installed")
def test_wrapping_a_pytest_selenium_driver_heals(selenium):
    """``selenium`` is pytest-selenium's own driver fixture. We wrap it in place."""
    from tamash_selenium import SelfHealingDriver, get_healing_reports
    from tamash_selenium.healer import heal_cache

    heal_cache.clear()
    driver = SelfHealingDriver.wrap(selenium)
    driver.get(_PAGE)

    username_field = (By.ID, "u-renamed")
    driver.find_element(*username_field).send_keys("ok")
    driver.find_element(By.ID, "go").click()
    assert driver.find_element(By.ID, "o").text == "ok"
    assert any(r.healed for r in get_healing_reports())


def test_both_plugins_load_without_fixture_collision():
    """Importing both plugin modules must not raise (the real risk was two plugins registering a
    ``driver`` fixture)."""
    import tamash_selenium.integrations.pytest_plugin  # noqa: F401
    if _HAS_PYTEST_SELENIUM:
        import pytest_selenium  # noqa: F401
