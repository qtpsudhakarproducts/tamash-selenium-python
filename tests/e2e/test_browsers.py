"""Healing works the same across browsers. ``TAMASH_BROWSER`` selects chrome / firefox / edge;
each is skipped if its binary / driver can't be provisioned on this machine."""

from __future__ import annotations

import pytest
from selenium.webdriver.common.by import By

pytestmark = pytest.mark.e2e

_PAGE = (
    "data:text/html,<form>"
    "<label for='u'>Username</label><input id='u' name='username'>"
    "<label for='p'>Password</label><input id='p' name='password' type='password'>"
    "<button id='go' type='button' onclick=\"document.getElementById('out').textContent='hi '+document.getElementById('u').value\">Log in</button>"
    "<div id='out'></div></form>"
)


@pytest.fixture(params=["chrome", "firefox", "edge"])
def browser_driver(request, monkeypatch, tmp_path):
    monkeypatch.setenv("TAMASH_BROWSER", request.param)
    monkeypatch.setenv("HEADLESS", "true")
    monkeypatch.chdir(tmp_path)
    from tamash_selenium.lifecycle import new_driver
    from tamash_selenium import SelfHealingDriver
    from tamash_selenium.healer import heal_cache

    try:
        raw = new_driver()
    except Exception as exc:  # noqa: BLE001 - browser/driver not available here
        pytest.skip(f"{request.param} not available: {str(exc).splitlines()[0][:120]}")
    heal_cache.clear()
    try:
        yield SelfHealingDriver.wrap(raw)
    finally:
        raw.quit()


def test_broken_locator_heals_on_every_browser(browser_driver):
    browser_driver.get(_PAGE)
    username_field = (By.ID, "the-username-box-renamed")
    browser_driver.find_element(*username_field).send_keys("admin")
    browser_driver.find_element(By.ID, "go").click()

    assert browser_driver.find_element(By.ID, "out").text == "hi admin"

    from tamash_selenium import get_healing_reports
    healed = [r for r in get_healing_reports() if r.healed and r.action == "findElement"]
    assert healed and "Username" in healed[-1].description
