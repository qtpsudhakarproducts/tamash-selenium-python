"""End-to-end: a real headless Chrome, the rule-based ``tamash`` provider (no key, no network)."""

from __future__ import annotations

import pytest
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from tests.conftest import FIXTURE_LOGIN

pytestmark = pytest.mark.e2e


def test_baseline_no_healing_needed(healing_driver):
    healing_driver.get(FIXTURE_LOGIN)
    healing_driver.find_element(By.ID, "username").send_keys("admin")
    healing_driver.find_element(By.ID, "submit").click()
    assert healing_driver.find_element(By.ID, "result").text == "hello admin"


def test_heals_broken_locator_via_descriptive_name(healing_driver):
    healing_driver.get(FIXTURE_LOGIN)
    username_field = (By.ID, "user_name_WRONG")
    healing_driver.find_element(*username_field).send_keys("tomsmith")
    assert healing_driver.find_element(By.ID, "username").get_attribute("value") == "tomsmith"

    from tamash_selenium import get_healing_reports
    reports = [r for r in get_healing_reports() if r.action == "findElement"]
    assert reports and reports[-1].healed and reports[-1].provider == "tamash"


def test_disabled_fails_natively(raw_chrome, monkeypatch):
    monkeypatch.setenv("HEALER_ENABLED", "false")
    from tamash_selenium import SelfHealingDriver
    from tamash_selenium.healer import heal_cache

    heal_cache.clear()
    driver = SelfHealingDriver.wrap(raw_chrome)
    driver.get(FIXTURE_LOGIN)
    username_field = (By.ID, "user_name_WRONG")
    with pytest.raises(NoSuchElementException):
        driver.find_element(*username_field).send_keys("x")


def test_find_elements_never_healed(healing_driver):
    healing_driver.get(FIXTURE_LOGIN)
    assert healing_driver.find_elements(By.ID, "does_not_exist") == []


def test_get_durable_upgrades_xpath(healing_driver):
    healing_driver.get(FIXTURE_LOGIN)
    from tamash_selenium import get_durable

    durable = get_durable(healing_driver, (By.XPATH, "//form/input[1]"), action="send_keys")
    assert durable in (("id", "username"), ("name", "username"))
